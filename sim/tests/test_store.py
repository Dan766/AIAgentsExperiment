import pytest

from driftwood.config import load_scenario
from driftwood.scoring import finalize
from driftwood.store import Store
from driftwood.world import World

from .test_game import JOBS, NAMES, thief_policy, worker_policy


def intents(world):
    out = {}
    for n in NAMES:
        a = thief_policy(world, n) if JOBS[n] == "thief" else worker_policy(world, n)
        if a:
            out[n] = a
    return out


def play_into(store, run_id, world, until=None):
    """Advance `world` to tick `until` (or the end), saving every tick. Returns all events."""
    log = []
    while not world.done and (until is None or world.tick < until):
        events = world.step(intents(world))
        store.save_tick(run_id, world, events, thoughts=[("A", f"thinking at {world.tick}")])
        log.extend(e.model_dump() for e in events)
    return log


@pytest.fixture
def store():
    s = Store()
    yield s
    s.close()


def new_run(store, seed=7):
    world = World.new(load_scenario(), NAMES, seed=seed)
    return world, store.create_run(world, label="test")


def test_run_registered_with_starting_snapshot(store):
    world, rid = new_run(store)
    assert store.get_run(rid)["seed"] == 7 and store.get_run(rid)["status"] == "running"
    assert store.latest_tick(rid) == 0
    assert store.load_world(rid) == world
    with pytest.raises(KeyError):
        store.load_world(rid, 5)
    with pytest.raises(KeyError):
        store.get_run(999)


def test_snapshot_roundtrip_is_exact_mid_game(store):
    world, rid = new_run(store)
    play_into(store, rid, world, until=20)
    restored = store.load_world(rid)
    assert restored.tick == 20 and restored == world
    assert restored.model_dump() == world.model_dump()
    assert any(s.inventory for s in restored.agents.values())  # not a trivial empty world


def test_restored_world_continues_identically(store):
    """The real guarantee: stop at tick 20, restore from the DB, finish; same as never stopping."""
    straight, rid1 = new_run(store)
    log_straight = play_into(store, rid1, straight)

    first, rid2 = new_run(store)
    log_a = play_into(store, rid2, first, until=20)
    resumed = store.load_world(rid2)
    log_b = play_into(store, rid2, resumed)

    assert log_a + log_b == log_straight
    assert resumed == straight and finalize(resumed) == finalize(straight)
    assert store.get_run(rid2)["status"] == "finished"


def test_every_tick_has_a_snapshot_and_can_be_loaded(store):
    world, rid = new_run(store)
    play_into(store, rid, world)
    assert store.latest_tick(rid) == 42
    for t in (0, 1, 13, 41, 42):
        assert store.load_world(rid, t).tick == t


def test_events_queryable_by_tick_kind_and_actor(store):
    world, rid = new_run(store)
    log = play_into(store, rid, world, until=10)
    at4 = store.events(rid, tick=4)
    assert at4 and all(e["tick"] == 4 and e["kind"] == "action" for e in at4)
    assert len(at4) == sum(1 for e in log if e["tick"] == 4)
    assert all(e["payload"]["actor"] == "A" for e in store.events(rid, actor="A"))
    assert len(store.events(rid)) == len(log)
    assert store.events(rid, tick=999) == []


def test_night_ticks_have_no_events_but_still_snapshot(store):
    world, rid = new_run(store)
    play_into(store, rid, world, until=6)
    assert store.events(rid, tick=5) == []  # tick 5 is night
    assert store.load_world(rid, 6).tick == 6


def test_custom_events_thoughts_and_beliefs(store):
    world, rid = new_run(store)
    store.add_event(rid, 3, "message", "B", {"channel": "group", "text": "hello"})
    store.add_event(rid, 3, "god", None, {"type": "storm"})
    assert [e["kind"] for e in store.events(rid, tick=3)] == ["message", "god"]
    assert store.events(rid, kind="message")[0]["payload"]["text"] == "hello"
    play_into(store, rid, world, until=2)
    assert store.thoughts(rid, agent="A")[0]["text"] == "thinking at 1"
    store.save_beliefs(rid, 1, "A", {"trust": {"B": 0.5}})
    store.save_beliefs(rid, 1, "A", {"trust": {"B": -0.2}})  # replaces
    assert store.beliefs(rid, day=1)[0]["payload"]["trust"]["B"] == -0.2


def test_extra_state_roundtrips_alongside_world(store):
    world, rid = new_run(store)
    world.step({})
    store.save_tick(rid, world, extra={"memories": {"A": ["saw B at the forest"]}})
    assert store.load_extra(rid)["memories"]["A"] == ["saw B at the forest"]
    assert store.load_extra(rid, 0) == {}


def test_forks_record_lineage_and_runs_are_isolated(store):
    world, rid = new_run(store)
    play_into(store, rid, world, until=12)
    fork_world = store.load_world(rid, 12)
    fid = store.create_run(fork_world, label="fork", parent_id=rid, fork_tick=12)
    play_into(store, fid, fork_world, until=14)
    run = store.get_run(fid)
    assert run["parent_id"] == rid and run["fork_tick"] == 12
    assert store.latest_tick(fid) == 14 and store.latest_tick(rid) == 12
    assert len(store.list_runs()) == 2
    assert all(e["tick"] >= 12 for e in store.events(fid))


def test_llm_call_log(store):
    world, rid = new_run(store)
    store.log_llm_call(rid, 1, "A", "decide", cache_key="k", latency_ms=5100, input_tokens=900,
                       output_tokens=60)
    store.log_llm_call(rid, 1, "B", "decide", ok=False, error="bad json")
    rows = store.db.execute("SELECT agent, ok, error FROM llm_calls ORDER BY id").fetchall()
    assert [(r["agent"], r["ok"], r["error"]) for r in rows] == [("A", 1, None), ("B", 0, "bad json")]


def test_file_backed_store_persists_across_connections(tmp_path):
    path = tmp_path / "runs.db"
    s1 = Store(path)
    world = World.new(load_scenario(), NAMES, seed=2)
    rid = s1.create_run(world)
    play_into(s1, rid, world, until=8)
    s1.close()
    s2 = Store(path)
    assert s2.latest_tick(rid) == 8 and s2.load_world(rid) == world
    s2.close()
