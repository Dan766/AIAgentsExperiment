import json

import pytest

from driftwood.config import load_scenario
from driftwood.engine import Engine
from driftwood.lineage import (NoModel, compare_runs, compare_summary, diverge_tick, replay_provider, replay_run,
                               tree, verify_replay)
from driftwood.llm.base import CacheMiss
from driftwood.llm.brain import BrainMock
from driftwood.llm.cache import CachedProvider
from driftwood.personas import load_personas
from driftwood.store import Store
from driftwood.world import World

PERSONAS = load_personas()
NAMES = [p.name for p in PERSONAS]
MOCK_META = dict(provider="mock", model="mock", cache_namespace="")


def root_engine(store, provider=None, seed=3, meta=None):
    return Engine.start(World.new(load_scenario(), NAMES, seed=seed), PERSONAS, provider or BrainMock(), store,
                        label="root", meta=meta if meta is not None else MOCK_META)


async def finished_parent(store, events=()):
    eng = root_engine(store)
    for type_, targets, params, at in events:
        eng.inject(type_, targets, params, at)
    await eng.run()
    return eng


# ---- forking -----------------------------------------------------------------------------------
async def test_fork_copies_history_up_to_the_tick_and_leaves_the_parent_alone():
    store = Store()
    eng = root_engine(store)
    eng.inject("broadcast", params={"text": "hello island"}, at_tick=3)
    await eng.run(until_tick=14)
    fork_id = store.fork_run(eng.run_id, 10)

    run = store.get_run(fork_id)
    assert run["parent_id"] == eng.run_id and run["fork_tick"] == 10 and run["provider"] == "mock"
    assert store.latest_tick(fork_id) == 10 and store.latest_tick(eng.run_id) == 14
    for t in range(0, 11):
        assert store.load_world(fork_id, t) == store.load_world(eng.run_id, t)
        assert store.load_extra(fork_id, t) == store.load_extra(eng.run_id, t)
    assert compare_runs(store, eng.run_id, fork_id, 0, 10) == []        # snapshots, events and thoughts all match
    assert [e["kind"] for e in store.events(fork_id, tick=2)] == [e["kind"] for e in store.events(eng.run_id, tick=2)]
    assert store.events(fork_id, tick=10) == [] and store.events(eng.run_id, tick=10) != []   # nothing from the future
    assert {b["day"] for b in store.beliefs(fork_id)} == {1}                                  # day-2 reflection is later
    assert store.get_run(eng.run_id)["status"] == "running" and store.latest_tick(eng.run_id) == 14


async def test_a_control_fork_reproduces_the_parent_exactly():
    store = Store()
    parent = await finished_parent(store)
    fork = Engine.fork(parent.run_id, 12, PERSONAS, BrainMock(), store)
    await fork.run()
    assert compare_runs(store, parent.run_id, fork.run_id, 0) == []
    assert diverge_tick(store, parent.run_id, fork.run_id) is None
    assert store.get_run(fork.run_id)["status"] == "finished"


async def test_a_fork_with_a_storm_diverges_exactly_at_the_fork_point():
    store = Store()
    parent = await finished_parent(store)
    fork = Engine.fork(parent.run_id, 16, PERSONAS, BrainMock(), store, label="storm")
    fork.inject("storm", params={"severity": 0.5}, at_tick=16)
    await fork.run()
    assert diverge_tick(store, parent.run_id, fork.run_id) == 16
    assert compare_runs(store, parent.run_id, fork.run_id, 0, 15) == []
    assert compare_runs(store, parent.run_id, fork.run_id, 16, 20) != []
    s = compare_summary(store, parent.run_id, fork.run_id)
    assert s["diverged_at_tick"] == 16 and s["raft"][0] != s["raft"][1]
    assert [e["payload"]["type"] for e in store.events(fork.run_id, kind="god")] == ["storm"]
    assert store.events(parent.run_id, kind="god") == []


async def test_forks_of_forks_form_a_tree():
    store = Store()
    parent = await finished_parent(store)
    a = store.fork_run(parent.run_id, 8, "branch A")
    b = store.fork_run(parent.run_id, 20, "branch B")
    c = store.fork_run(a, 8, "branch A1")
    assert [r["id"] for r in store.children(parent.run_id)] == [a, b]
    assert store.get_run(c)["parent_id"] == a
    text = tree(store)
    lines = text.splitlines()
    assert lines[0].startswith("#1 root") and "branch A" in lines[1] and lines[1].startswith("  └─")
    assert any(line.startswith("    └─") and "branch A1" in line for line in lines)  # grandchild is indented deeper
    assert "forked at tick 20" in text


async def test_fork_rejects_a_tick_the_run_never_reached():
    store = Store()
    eng = root_engine(store)
    await eng.run(until_tick=5)
    with pytest.raises(ValueError, match="no tick 9"):
        store.fork_run(eng.run_id, 9)
    store.fork_run(eng.run_id, 5)  # the latest tick itself is fine


# ---- exact replay --------------------------------------------------------------------------------
async def test_replay_reproduces_a_run_with_god_events_exactly():
    store = Store()
    parent = await finished_parent(store, [
        ("rumor", ["Theo"], {"text": "Elliot hides gold"}, 8),
        ("storm", "all", {"severity": 0.3}, 16),
        ("set_seats", "all", {"seats": 5}, 20),
        ("whisper", ["Rosa"], {"text": "check the pile"}, 0),     # applied at the very first tick
    ])
    v = await verify_replay(store, parent.run_id, PERSONAS, ":memory:")
    assert v.ok, v.mismatches
    assert (v.start_tick, v.end_tick) == (0, 43) and v.replay_run_id != parent.run_id
    # the tick-0 whisper is already baked into the snapshot the replay resumes from, so only 3 are re-queued
    assert [g["type"] for g in store.god_events(v.replay_run_id)] == ["rumor", "storm", "set_seats"]


async def test_replay_notices_when_the_original_record_was_altered():
    store = Store()
    parent = await finished_parent(store)
    row = store.db.execute("SELECT id, payload FROM events WHERE run_id = ? AND kind = 'action' AND tick = 4 LIMIT 1",
                           (parent.run_id,)).fetchone()
    doctored = json.loads(row["payload"])
    doctored["ok"] = not doctored["ok"]
    store.db.execute("UPDATE events SET payload = ? WHERE id = ?", (json.dumps(doctored), row["id"]))
    store.db.commit()
    v = await verify_replay(store, parent.run_id, PERSONAS, ":memory:")
    assert not v.ok and any("tick 4: events differ" in m for m in v.mismatches)


async def test_replay_of_a_fork_that_carries_its_own_god_event():
    store = Store()
    parent = await finished_parent(store)
    fork = Engine.fork(parent.run_id, 16, PERSONAS, BrainMock(), store)
    fork.inject("storm", params={"severity": 0.4}, at_tick=16)           # applied at the fork tick itself
    fork.inject("broadcast", params={"text": "later news"}, at_tick=25)
    await fork.run()
    v = await verify_replay(store, fork.run_id, PERSONAS, ":memory:")
    assert v.ok, v.mismatches
    assert v.start_tick == 16


# ---- cache-served replay (the real-model path, with a fake model) ----------------------------------
async def test_replay_from_the_cache_makes_zero_model_calls(tmp_path):
    cache = tmp_path / "cache.db"
    store = Store()
    recorder = CachedProvider(BrainMock(), cache, mode="cached")
    eng = root_engine(store, recorder, meta=dict(provider="cli", model="mock", cache_namespace=""))
    eng.inject("storm", params={"severity": 0.2}, at_tick=9)
    await eng.run()
    recorder.close()

    run = store.get_run(eng.run_id)
    provider = replay_provider(run, str(cache))
    assert isinstance(provider, CachedProvider) and isinstance(provider.inner, NoModel)
    v = await verify_replay(store, eng.run_id, PERSONAS, str(cache))
    assert v.ok, v.mismatches

    with pytest.raises(CacheMiss):                                       # a cache that lacks the run cannot replay it
        await verify_replay(store, eng.run_id, PERSONAS, str(tmp_path / "empty.db"))


class Wobbly(BrainMock):
    """A deliberately non-deterministic agent: every `period`-th call it just rests, like sampling noise."""

    def __init__(self, offset, period=4):
        super().__init__()
        self.n, self.period = offset, period
        self.inner_script = self.script
        self.script = self._wobble

    def _wobble(self, system, prompt):
        self.n += 1
        if self.n % self.period == 0 and "LOCATION" in prompt:
            return json.dumps({"thought": "tired", "action": {"type": "rest"}, "messages": []})
        return self.inner_script(system, prompt)


async def test_fresh_samples_differ_and_each_one_replays_exactly(tmp_path):
    cache = tmp_path / "cache.db"
    store = Store()
    meta = dict(provider="cli", model="mock", cache_namespace="")
    parent = root_engine(store, CachedProvider(BrainMock(), cache, mode="cached"), meta=meta)
    await parent.run(until_tick=6)

    forks = []
    for k, offset in enumerate((0, 1)):
        ns = f"|sample{k}"
        prov = CachedProvider(Wobbly(offset), cache, mode="fresh", namespace=ns)
        f = Engine.fork(parent.run_id, 6, PERSONAS, prov, store, label=f"sample {k}", cache_namespace=ns)
        await f.run(until_tick=18)
        forks.append(f)
    a, b = forks
    assert store.get_run(a.run_id)["cache_namespace"] == "|sample0"
    assert diverge_tick(store, a.run_id, b.run_id) is not None           # sampling noise really changes the outcome
    for f in forks:                                                      # ...but each sample replays exactly
        v = await verify_replay(store, f.run_id, PERSONAS, str(cache))
        assert v.ok, v.mismatches


async def test_replay_run_is_a_new_run_and_never_touches_the_original():
    store = Store()
    parent = await finished_parent(store)
    before = store.load_world(parent.run_id).model_dump()
    new_id, _ = await replay_run(store, parent.run_id, PERSONAS, BrainMock())
    assert new_id != parent.run_id and store.get_run(new_id)["parent_id"] is None
    assert store.load_world(parent.run_id).model_dump() == before
    assert "replay of run" in store.get_run(new_id)["label"]


# ---- the command line -----------------------------------------------------------------------------
def test_cli_runs_fork_compare_and_replay_end_to_end(tmp_path, capsys):
    from driftwood.cli import main
    db, cache = str(tmp_path / "r.db"), str(tmp_path / "c.db")

    def cli(*argv):
        with pytest.raises(SystemExit) as e:
            main(list(argv))
        return e.value.code

    assert cli("run", "--provider", "mock", "--db", db, "--cache", cache, "--seed", "5", "--label", "base") == 0
    assert cli("fork", "1", "--tick", "10", "--event", "storm", "--params", '{"severity":0.5}', "--provider", "mock",
               "--db", db, "--cache", cache) == 0
    out = capsys.readouterr().out
    assert "forked run #2 from #1 at tick 10" in out and "launched:" in out
    assert cli("compare", "1", "2", "--db", db) == 0
    assert "worlds first differ at tick 10" in capsys.readouterr().out
    assert cli("runs", "--db", db) == 0
    listing = capsys.readouterr().out
    assert "#1 base" in listing and "└─ #2" in listing and "forked at tick 10" in listing
    assert cli("replay", "1", "--db", db, "--cache", cache) == 0
    assert "IDENTICAL to the original" in capsys.readouterr().out
    assert cli("replay", "2", "--db", db, "--cache", cache) == 0
    assert "IDENTICAL" in capsys.readouterr().out
    assert cli("fork", "1", "--tick", "99", "--no-run", "--provider", "mock", "--db", db) == 1
    assert "no tick 99" in capsys.readouterr().err


# ---- replay must survive later changes to validation rules (found on the real game 1 fork) -------------
@pytest.fixture
def restore_limits():
    from driftwood import turn
    saved = dict(turn.LIMITS)
    yield turn.LIMITS
    turn.LIMITS.clear()
    turn.LIMITS.update(saved)


def _long_message_script():
    """Ama's first reply on day 2 morning has an 800-character message (rejected under a 600 limit, fine under 900);
    when the harness retries with the rejection, she sends a short one."""
    from driftwood.llm.brain import mock_brain

    def script(system, prompt):
        out = json.loads(mock_brain(system, prompt))
        if "You are Ama," in system and "DAY 2 of 7, MORNING" in prompt:
            text = "x " * 400 if "rejected" not in prompt else "short and sweet"
            out["messages"] = [{"channel": "group", "text": text}]
        return json.dumps(out)

    return script


async def test_changing_a_validation_limit_later_does_not_break_replay(tmp_path, restore_limits):
    from driftwood.llm.mock import MockProvider

    cache = tmp_path / "cache.db"
    restore_limits["message_chars"] = 600
    store = Store()
    recorder = CachedProvider(MockProvider(_long_message_script()), cache, mode="cached")
    eng = root_engine(store, recorder, meta=dict(provider="cli", model="mock", cache_namespace=""))
    await eng.run(until_tick=14)
    assert eng.stats.first_try_invalid == 1                                  # the long reply really was rejected
    assert json.loads(store.get_run(eng.run_id)["rules"]) == {"message_chars": 600}
    ama_msgs = [e["payload"]["text"] for e in store.events(eng.run_id, kind="message", actor="Ama")]
    assert "short and sweet" in ama_msgs and not any(len(t) > 600 for t in ama_msgs)

    restore_limits["message_chars"] = 900                                    # a later code change loosens the limit
    v = await verify_replay(store, eng.run_id, PERSONAS, str(cache))
    assert v.ok, v.mismatches                                                # the run's own recorded rules win
    fork = Engine.fork(eng.run_id, 8, PERSONAS, CachedProvider(NoModel("mock"), cache, mode="replay"), store)
    await fork.run(until_tick=14)                                            # a fork inherits them too
    assert compare_runs(store, eng.run_id, fork.run_id, 0, 14) == []


async def test_without_recorded_rules_the_same_change_breaks_replay(tmp_path, restore_limits):
    """Documents the hazard the rules column exists to prevent."""
    from driftwood.llm.mock import MockProvider

    cache = tmp_path / "cache.db"
    restore_limits["message_chars"] = 600
    store = Store()
    eng = root_engine(store, CachedProvider(MockProvider(_long_message_script()), cache, mode="cached"),
                      meta=dict(provider="cli", model="mock", cache_namespace=""))
    await eng.run(until_tick=14)
    store.db.execute("UPDATE runs SET rules = '{}' WHERE id = ?", (eng.run_id,))   # pretend it predates the column
    store.db.commit()
    restore_limits["message_chars"] = 900
    with pytest.raises(CacheMiss):
        await verify_replay(store, eng.run_id, PERSONAS, str(cache))
