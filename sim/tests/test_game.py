"""Plays full 42-tick games with scripted (non-LLM) agents and checks determinism."""
from driftwood.actions import (Build, Gather, Move, SearchWreck, Stash, Take, Tamper, Vote)
from driftwood.config import load_scenario
from driftwood.scoring import finalize
from driftwood.world import World

NAMES = ["A", "B", "C", "D", "E", "F", "G", "H"]
JOBS = {"A": "wood", "B": "wood", "C": "wood", "D": "wreck", "E": "wreck", "F": "wreck",
        "G": "food", "H": "thief"}


def worker_policy(world, name):
    """Gather for the raft, build whatever you are carrying."""
    me, inv = world.agents[name], world.agents[name].inventory
    sc = world.scenario
    if world.tick == sc.vote_tick:
        return Vote(names=NAMES[:6])
    for comp, c in sc.recipe.items():
        carrying = inv.get(c.resource, 0)
        full = world.raft[comp] >= c.need
        if carrying >= (4 if c.resource != "food" else 3) and not full:
            return Build(component=comp) if me.location == "build_site" else Move(location="build_site")
    job = JOBS[name]
    if job == "wood":
        return Gather(resource="wood") if me.location == "forest" else Move(location="forest")
    if job == "food":
        return Gather(resource="food") if me.location == "lagoon" else Move(location="lagoon")
    if job == "wreck":
        for comp in ("lashings", "sail"):  # leftovers once a component is full
            c = sc.recipe[comp]
            if inv.get(c.resource, 0) and world.raft[comp] < c.need and me.location == "build_site":
                return Build(component=comp)
        if inv.get("gold", 0) >= 1 and me.location == "wreck":
            return Stash(item="gold", n=inv["gold"])
        return SearchWreck() if me.location == "wreck" else Move(location="wreck")
    return None


def thief_policy(world, name):
    """H shadows a wreck agent and steals gold; sabotages the hull once it has some progress."""
    me = world.agents[name]
    if world.tick == world.scenario.vote_tick:
        return Vote(names=NAMES[:6])
    target = next((a for a in "DEF" if world.agents[a].inventory.get("gold")), None)
    if target and world.agents[target].location == me.location:
        return Take(agent=target, item="gold", n=99)
    if world.raft["hull"] > 12 and world.raft["hull"] < 24:
        return Tamper(component="hull") if me.location == "build_site" else Move(location="build_site")
    return Move(location="wreck") if me.location != "wreck" else None


def play(seed):
    world = World.new(load_scenario(), NAMES, seed=seed)
    log = []
    while not world.done:
        intents = {}
        for n in NAMES:
            a = thief_policy(world, n) if JOBS[n] == "thief" else worker_policy(world, n)
            if a:
                intents[n] = a
        log.extend(e.model_dump() for e in world.step(intents))
    return world, log, finalize(world)


def test_full_game_launches_with_expected_structure():
    world, log, out = play(seed=7)
    assert world.done and world.tick == 42
    assert out.launched, world.raft
    assert set(out.seats) == set(NAMES[:6])
    assert all(out.scores[n] >= 100 for n in out.seats)
    assert out.scores["G"] == out.scores["H"] == 0
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
