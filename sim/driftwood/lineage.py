"""Replay, verify and compare runs. Together with fork_run this is the experimental toolkit:
fork a moment, change one thing, and diff the two futures; or replay a run from cache and prove it reproduces."""
import json
from dataclasses import dataclass, field

from .engine import Engine
from .llm.base import CacheMiss, LLMResponse, Provider
from .llm.brain import BrainMock
from .llm.cache import CachedProvider
from .personas import Persona
from .report import build_report
from .store import Store


class NoModel:
    """Inner provider for replay: any real model call is a bug, so fail loudly."""

    def __init__(self, model: str):
        self.model = model

    async def complete(self, system: str, prompt: str) -> LLMResponse:
        raise CacheMiss("replay must be served entirely from the cache")


def replay_provider(run: dict, cache_path: str) -> Provider:
    """The provider that reproduces `run` without spending quota."""
    if run["provider"] == "mock":
        return BrainMock()
    return CachedProvider(NoModel(run["model"] or "haiku"), cache_path, mode="replay",
                          namespace=run["cache_namespace"])


@dataclass
class Verification:
    ok: bool
    replay_run_id: int
    start_tick: int
    end_tick: int
    mismatches: list[str] = field(default_factory=list)


async def replay_run(store: Store, run_id: int, personas: list[Persona], provider: Provider,
                     label: str | None = None) -> tuple[int, Engine]:
    """Re-run `run_id` from its first tick (or its fork point) into a NEW run, re-injecting the same god events
    at the same ticks. With a replay-mode provider this costs nothing and must reproduce the original."""
    run = store.get_run(run_id)
    start = run["fork_tick"] or 0
    world, extra = store.load_world(run_id, start), store.load_extra(run_id, start)
    new_id = store.create_run(world, label=label or f"replay of run {run_id}", extra=extra,
                              provider=run["provider"], model=run["model"], cache_namespace=run["cache_namespace"],
                              rules=json.loads(run["rules"] or "{}"))
    engine = Engine.resume(new_id, personas, provider, store)
    for g in store.god_events(run_id):
        # events applied exactly at `start` are already baked into the snapshot we resumed from
        if g["status"] == "applied" and g["applied_tick"] is not None and g["applied_tick"] > start:
            store.add_god_event(new_id, g["type"], g["targets"], g["params"], at_tick=g["applied_tick"])
    await engine.run(until_tick=store.latest_tick(run_id))
    return new_id, engine


def _diff_keys(a: dict, b: dict) -> list[str]:
    return sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))


def compare_runs(store: Store, a: int, b: int, start: int = 0, end: int | None = None, limit: int = 12) -> list[str]:
    """Exact comparison of two runs over [start, end]: snapshots (world + agent memory/beliefs), events and thoughts."""
    out: list[str] = []

    def note(msg: str):
        if len(out) < limit:
            out.append(msg)

    if end is None:
        if store.latest_tick(a) != store.latest_tick(b):
            note(f"different lengths: {store.latest_tick(a)} vs {store.latest_tick(b)}")
        end = min(store.latest_tick(a), store.latest_tick(b))
    for t in range(start, end + 1):
        wa, wb = store.load_world(a, t).model_dump(), store.load_world(b, t).model_dump()
        if wa != wb:
            note(f"tick {t}: world differs in {_diff_keys(wa, wb)}")
        ea, eb = store.load_extra(a, t), store.load_extra(b, t)
        if ea != eb:
            who = _diff_keys(ea.get("agents", {}), eb.get("agents", {}))
            note(f"tick {t}: agent state differs for {who}")
        if t < end:
            for table in ("events", "thoughts"):
                ra = [_row(r, table) for r in _rows(store, table, a, t)]
                rb = [_row(r, table) for r in _rows(store, table, b, t)]
                if ra != rb:
                    note(f"tick {t}: {table} differ ({len(ra)} vs {len(rb)} rows)")
    return out


def _rows(store: Store, table: str, run_id: int, tick: int):
    return store.db.execute(f"SELECT * FROM {table} WHERE run_id = ? AND tick = ? ORDER BY id", (run_id, tick)).fetchall()


def _row(r, table: str):
    return (r["kind"], r["actor"], r["payload"]) if table == "events" else (r["agent"], r["text"])


def diverge_tick(store: Store, a: int, b: int) -> int | None:
    """First tick at which the two runs' worlds differ, or None if identical over their common range."""
    for t in range(0, min(store.latest_tick(a), store.latest_tick(b)) + 1):
        if store.load_world(a, t).model_dump() != store.load_world(b, t).model_dump():
            return t
    return None


async def verify_replay(store: Store, run_id: int, personas: list[Persona], cache_path: str) -> Verification:
    """Replay a run from the cache and prove it matches the original, tick for tick."""
    run = store.get_run(run_id)
    start, end = run["fork_tick"] or 0, store.latest_tick(run_id)
    new_id, _ = await replay_run(store, run_id, personas, replay_provider(run, cache_path))
    bad = compare_runs(store, run_id, new_id, start, end)
    return Verification(not bad, new_id, start, end, bad)


def compare_summary(store: Store, a: int, b: int) -> dict:
    ra, rb = build_report(store, a), build_report(store, b)
    sab = lambda r: sum(1 for s in r["sabotage"] if s["ok"])  # noqa: E731
    return {
        "diverged_at_tick": diverge_tick(store, a, b),
        "launched": (ra["launched"], rb["launched"]),
        "seats": (ra["seats"], rb["seats"]),
        "raft": (ra["raft"], rb["raft"]),
        "scores": {n: (ra["agents"][n]["score"], rb["agents"][n]["score"]) for n in ra["agents"]},
        "successful_sabotage": (sab(ra), sab(rb)),
        "cooperative_acts": (ra["cooperative_acts"], rb["cooperative_acts"]),
    }


def tree(store: Store) -> str:
    runs = store.list_runs()
    kids: dict = {}
    for r in runs:
        kids.setdefault(r["parent_id"], []).append(r)
    lines: list[str] = []

    def show(r: dict, depth: int):
        t = store.latest_tick(r["id"])
        total = store.load_world(r["id"], t).scenario.total_ticks
        fork = f" (forked at tick {r['fork_tick']})" if r["parent_id"] else ""
        ns = f" [{r['cache_namespace']}]" if r["cache_namespace"] else ""
        lines.append(f"{'  ' * depth}{'└─ ' if depth else ''}#{r['id']} {r['label'] or '(no label)'}{fork}  "
                     f"{r['status']} t{t}/{total}  seed {r['seed']}{ns}")
        for c in kids.get(r["id"], []):
            show(c, depth + 1)

    for root in kids.get(None, []):
        show(root, 0)
    return "\n".join(lines)
