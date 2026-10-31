"""Plays full 43-tick games (7 days + the ballot tick) with scripted (non-LLM) agents and checks determinism."""
from driftwood.config import load_scenario
from driftwood.scoring import finalize
from driftwood.world import World

from driftwood.demo import JOBS, NAMES, intents, thief_policy, worker_policy  # noqa: E402,F401


def play(seed):
    world = World.new(load_scenario(), NAMES, seed=seed)
    log = []
    while not world.done:
        log.extend(e.model_dump() for e in world.step(intents(world)))
    return world, log, finalize(world)


def test_full_game_launches_with_expected_structure():
    world, log, out = play(seed=7)
    assert world.done and world.tick == 43
    assert out.launched, world.raft
    assert set(out.seats) == set(NAMES[:6])
    assert all(out.scores[n] >= 100 for n in out.seats)
    assert out.scores["Ama"] == out.scores["Viktor"] == 0
    assert sum(1 for e in log if e["action"] == "vote" and e["ok"]) == 8


def test_same_seed_is_bit_for_bit_identical():
    w1, log1, out1 = play(seed=7)
    w2, log2, out2 = play(seed=7)
    assert log1 == log2 and out1 == out2 and w1.model_dump() == w2.model_dump()


def test_different_seed_diverges():
    _, log1, _ = play(seed=7)
    _, log2, _ = play(seed=8)
    assert log1 != log2


def test_unfinished_raft_scores_zero_for_everyone():
    world = World.new(load_scenario(), NAMES, seed=1)
    while not world.done:
        world.step({})
    out = finalize(world)
    assert not out.launched and set(out.scores.values()) == {0}


def test_cooperation_baseline_seats_everyone():
    sc = load_scenario(raft_seats=8, gold_value=0)
    world = World.new(sc, NAMES, seed=1)
    world.raft = {c: comp.need for c, comp in sc.recipe.items()}
    world.ballots = {n: NAMES for n in NAMES}
    out = finalize(world)
    assert set(out.seats) == set(NAMES) and set(out.scores.values()) == {100}
