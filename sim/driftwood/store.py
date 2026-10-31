"""SQLite persistence: runs form a fork tree, every tick leaves events plus a full world snapshot.

Snapshot convention: the snapshot stored under `tick = t` is the world after t ticks have run
(`world.tick == t`). Snapshot 0 is written when the run is created. Events carry the tick they
happened in (so events of tick t are produced between snapshot t and snapshot t+1).
"""
import json
import sqlite3
import time
from pathlib import Path
from typing import Iterable

from .actions import Event
from .world import World

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    parent_id INTEGER REFERENCES runs(id),
    fork_tick INTEGER,
    seed INTEGER NOT NULL,
    label TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'running',   -- running | paused | finished
    created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS ticks (
    run_id INTEGER NOT NULL REFERENCES runs(id),
    tick INTEGER NOT NULL,
    ts REAL NOT NULL,
    PRIMARY KEY (run_id, tick)
);
CREATE TABLE IF NOT EXISTS events (          -- actions, messages, observations, god events
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES runs(id),
    tick INTEGER NOT NULL,
    kind TEXT NOT NULL,                       -- action | message | observation | god | system
    actor TEXT,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS events_run_tick ON events(run_id, tick);
CREATE TABLE IF NOT EXISTS thoughts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES runs(id),
    tick INTEGER NOT NULL,
    agent TEXT NOT NULL,
    text TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS thoughts_run_tick ON thoughts(run_id, tick);
CREATE TABLE IF NOT EXISTS snapshots (
    run_id INTEGER NOT NULL REFERENCES runs(id),
    tick INTEGER NOT NULL,
    world TEXT NOT NULL,
    extra TEXT NOT NULL DEFAULT '{}',         -- non-world state (agent memories etc.), added in Phase 4
    PRIMARY KEY (run_id, tick)
);
CREATE TABLE IF NOT EXISTS beliefs (
    run_id INTEGER NOT NULL REFERENCES runs(id),
    day INTEGER NOT NULL,
    agent TEXT NOT NULL,
    payload TEXT NOT NULL,                    -- {trust: {name: -1..1}, suspicions: ..., facts: [...]}
    PRIMARY KEY (run_id, day, agent)
);
CREATE TABLE IF NOT EXISTS llm_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER REFERENCES runs(id),
    tick INTEGER,
    agent TEXT,
    purpose TEXT,                             -- decide | reflect | analyze
    cache_key TEXT,
    cache_hit INTEGER NOT NULL DEFAULT 0,
    latency_ms INTEGER,
    input_tokens INTEGER,
    output_tokens INTEGER,
    ok INTEGER NOT NULL DEFAULT 1,
    error TEXT
);
"""


class Store:
    def __init__(self, path: str | Path = ":memory:"):
        self.db = sqlite3.connect(str(path))
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        if str(path) != ":memory:":
            self.db.execute("PRAGMA journal_mode = WAL")
        self.db.executescript(SCHEMA)

    def close(self):
        self.db.close()

    # ---- runs ----------------------------------------------------------------------------
    def create_run(self, world: World, label: str = "", parent_id: int | None = None,
                   fork_tick: int | None = None) -> int:
        """Register a run and write its starting snapshot (at world.tick)."""
        with self.db:
            cur = self.db.execute(
                "INSERT INTO runs (parent_id, fork_tick, seed, label, created) VALUES (?,?,?,?,?)",
                (parent_id, fork_tick, world.seed, label, time.time()),
            )
            run_id = cur.lastrowid
            self._write_snapshot(run_id, world)
        return run_id

    def get_run(self, run_id: int) -> dict:
        row = self.db.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(f"no run {run_id}")
        return dict(row)

    def list_runs(self) -> list[dict]:
        return [dict(r) for r in self.db.execute("SELECT * FROM runs ORDER BY id")]

    def set_status(self, run_id: int, status: str):
        with self.db:
            self.db.execute("UPDATE runs SET status = ? WHERE id = ?", (status, run_id))

    # ---- ticks ---------------------------------------------------------------------------
    def save_tick(self, run_id: int, world: World, events: Iterable[Event] = (),
                  thoughts: Iterable[tuple[str, str]] = (), extra: dict | None = None,
                  extra_events: Iterable[tuple[str, str | None, dict]] = ()):
        """Atomically record one finished tick. `world.tick` is already advanced, so the snapshot is
        stored under world.tick and the events under the tick that just ran (world.tick - 1)."""
        ran = world.tick - 1
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO ticks (run_id, tick, ts) VALUES (?,?,?)",
                            (run_id, ran, time.time()))
            for ev in events:
                self._insert_event(run_id, ev.tick, "action", ev.actor, ev.model_dump_json())
            for kind, actor, payload in extra_events:
                self._insert_event(run_id, ran, kind, actor, json.dumps(payload))
            for agent, text in thoughts:
                self.db.execute("INSERT INTO thoughts (run_id, tick, agent, text) VALUES (?,?,?,?)",
                                (run_id, ran, agent, text))
            self._write_snapshot(run_id, world, extra)
            if world.done:
                self.db.execute("UPDATE runs SET status = 'finished' WHERE id = ?", (run_id,))

    def add_event(self, run_id: int, tick: int, kind: str, actor: str | None, payload: dict):
        """Record a non-action event (message, observation, god event, system note)."""
        with self.db:
            self._insert_event(run_id, tick, kind, actor, json.dumps(payload))

    def _insert_event(self, run_id, tick, kind, actor, payload: str):
        self.db.execute("INSERT INTO events (run_id, tick, kind, actor, payload) VALUES (?,?,?,?,?)",
                        (run_id, tick, kind, actor, payload))

    def _write_snapshot(self, run_id: int, world: World, extra: dict | None = None):
        self.db.execute(
            "INSERT OR REPLACE INTO snapshots (run_id, tick, world, extra) VALUES (?,?,?,?)",
            (run_id, world.tick, world.model_dump_json(), json.dumps(extra or {})),
        )

    def latest_tick(self, run_id: int) -> int:
        """Highest snapshot tick, i.e. how many ticks the run has completed."""
        row = self.db.execute("SELECT MAX(tick) FROM snapshots WHERE run_id = ?", (run_id,)).fetchone()
        return row[0]

    # ---- reading back --------------------------------------------------------------------
    def load_world(self, run_id: int, tick: int | None = None) -> World:
        """Restore the world after `tick` ticks (default: the latest snapshot)."""
        return World.model_validate_json(self._snapshot_row(run_id, tick)["world"])

    def load_extra(self, run_id: int, tick: int | None = None) -> dict:
        return json.loads(self._snapshot_row(run_id, tick)["extra"])

    def _snapshot_row(self, run_id: int, tick: int | None):
        if tick is None:
            tick = self.latest_tick(run_id)
        row = self.db.execute("SELECT * FROM snapshots WHERE run_id = ? AND tick = ?",
                              (run_id, tick)).fetchone()
        if row is None:
            raise KeyError(f"run {run_id} has no snapshot at tick {tick}")
        return row

    def events(self, run_id: int, tick: int | None = None, kind: str | None = None,
               actor: str | None = None) -> list[dict]:
        """Events in insertion order, each as {id, tick, kind, actor, payload(dict)}."""
        sql, args = "SELECT * FROM events WHERE run_id = ?", [run_id]
        for col, val in (("tick", tick), ("kind", kind), ("actor", actor)):
            if val is not None:
                sql += f" AND {col} = ?"
                args.append(val)
        rows = self.db.execute(sql + " ORDER BY id", args).fetchall()
        return [{**dict(r), "payload": json.loads(r["payload"])} for r in rows]

    def thoughts(self, run_id: int, tick: int | None = None, agent: str | None = None) -> list[dict]:
        sql, args = "SELECT * FROM thoughts WHERE run_id = ?", [run_id]
        for col, val in (("tick", tick), ("agent", agent)):
            if val is not None:
                sql += f" AND {col} = ?"
                args.append(val)
        return [dict(r) for r in self.db.execute(sql + " ORDER BY id", args)]

    def save_beliefs(self, run_id: int, day: int, agent: str, payload: dict):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO beliefs (run_id, day, agent, payload) VALUES (?,?,?,?)",
                            (run_id, day, agent, json.dumps(payload)))

    def beliefs(self, run_id: int, day: int | None = None) -> list[dict]:
        sql, args = "SELECT * FROM beliefs WHERE run_id = ?", [run_id]
        if day is not None:
            sql += " AND day = ?"
            args.append(day)
        rows = self.db.execute(sql + " ORDER BY day, agent", args)
        return [{**dict(r), "payload": json.loads(r["payload"])} for r in rows]

    def log_llm_call(self, run_id: int | None, tick: int | None, agent: str | None, purpose: str,
                     cache_key: str | None = None, cache_hit: bool = False,
                     latency_ms: int | None = None, input_tokens: int | None = None,
                     output_tokens: int | None = None, ok: bool = True, error: str | None = None):
        with self.db:
            self.db.execute(
                "INSERT INTO llm_calls (run_id, tick, agent, purpose, cache_key, cache_hit, latency_ms,"
                " input_tokens, output_tokens, ok, error) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (run_id, tick, agent, purpose, cache_key, int(cache_hit), latency_ms, input_tokens,
                 output_tokens, int(ok), error),
            )
