import random

import pytest

from driftwood.actions import (Build, Deposit, Eat, Gather, Give, Move, Rest, SearchWreck, Stash,
                               Take, Tamper, Unstash, Vote, Withdraw, parse_action, resolve)
from driftwood.config import load_scenario
from driftwood.scoring import finalize
from driftwood.world import World

NAMES = ["A", "B", "C", "D", "E", "F", "G", "H"]


@pytest.fixture
def world():
    return World.new(load_scenario(), NAMES, seed=1)


def run(world, who, action, seed=0):
    return resolve(world, who, action, random.Random(seed))


def put(world, who, **items):
    world.agents[who].inventory.update(items)


def at(world, loc, *who):
    for w in who:
        world.agents[w].location = loc


def test_parse_action_discriminates():
    assert isinstance(parse_action({"type": "gather", "resource": "wood"}), Gather)
    with pytest.raises(Exception):
        parse_action({"type": "teleport"})


def test_move_costs_energy_and_is_witnessed(world):
    at(world, "camp", "A", "B")
    at(world, "lookout", *NAMES[2:])
    ev = run(world, "A", Move(location="forest"))
    assert ev.ok and world.agents["A"].location == "forest"
    assert world.agents["A"].energy == 100 - 5
    assert ev.seen_by == ["B"]
    assert not run(world, "A", Move(location="forest")).ok  # already there
    assert not run(world, "A", Move(location="moon")).ok


def test_gather_only_what_the_place_yields(world):
    at(world, "forest", "A")
    ev = run(world, "A", Gather(resource="wood"))
    assert ev.ok and 2 <= world.agents["A"].inventory["wood"] <= 4
    assert not run(world, "A", Gather(resource="rope")).ok
    at(world, "camp", "A")
    assert not run(world, "A", Gather(resource="wood")).ok


def test_scarcity_multiplier_applies(world):
    world.yield_mult["wood"] = 0.0
    at(world, "forest", "A")
    ev = run(world, "A", Gather(resource="wood"))
    assert ev.ok and "wood" not in world.agents["A"].inventory


def test_exhaustion_blocks_actions(world):
    at(world, "forest", "A")
    world.agents["A"].energy = 5
    ev = run(world, "A", Gather(resource="wood"))
    assert not ev.ok and ev.reason == "too tired"
    assert world.agents["A"].energy == 5


def test_search_wreck_hides_haul_from_witnesses(world):
    at(world, "wreck", "A", "B")
    ev = run(world, "A", SearchWreck())
    assert ev.ok and ev.public == {} and ev.seen_by == ["B"]
    assert not run(world, "C", SearchWreck()).ok  # C is at camp


def test_wreck_gold_is_finite(world):
    world.wreck_gold_left = 1
    world.scenario.wreck.gold_chance = 1.0
    at(world, "wreck", "A")
    run(world, "A", SearchWreck())
    assert world.agents["A"].inventory["gold"] == 1 and world.wreck_gold_left == 0
    run(world, "A", SearchWreck(), seed=2)
    assert world.agents["A"].inventory["gold"] == 1


def test_build_caps_at_rate_and_need_and_tracks_contribution(world):
    at(world, "build_site", "A")
    put(world, "A", wood=30)
    ev = run(world, "A", Build(component="hull"))
    assert ev.ok and world.raft["hull"] == 4 and world.agents["A"].inventory["wood"] == 26
    assert world.contrib["A"] == {"hull": 4}
    world.raft["hull"] = 22
    run(world, "A", Build(component="hull"))
    assert world.raft["hull"] == 24
    ev = run(world, "A", Build(component="hull"))
    assert not ev.ok and "complete" in ev.reason
    assert not run(world, "A", Build(component="sail")).ok  # no cloth
    at(world, "camp", "A")
    assert not run(world, "A", Build(component="hull")).ok


def test_deposit_withdraw_only_at_camp(world):
    put(world, "A", wood=5)
    assert run(world, "A", Deposit(item="wood", n=3)).ok
    assert world.stockpile == {"wood": 3} and world.agents["A"].inventory == {"wood": 2}
    assert run(world, "B", Withdraw(item="wood", n=2)).ok
    assert world.stockpile == {"wood": 1}
    assert not run(world, "B", Withdraw(item="wood", n=5)).ok
    at(world, "forest", "A")
    assert not run(world, "A", Deposit(item="wood")).ok


def test_give_needs_colocation_and_items(world):
    put(world, "A", food=3)
    at(world, "forest", "B")
    assert not run(world, "A", Give(person="B", item="food", n=1)).ok
    at(world, "forest", "A")
    assert run(world, "A", Give(person="B", item="food", n=2)).ok
    assert world.agents["B"].inventory["food"] == 2 and world.agents["A"].inventory["food"] == 1
    assert not run(world, "A", Give(person="B", item="food", n=5)).ok


def test_take_moves_items_and_detection_is_probabilistic(world):
    world.scenario.take_detect_p = 1.0
    put(world, "B", gold=4)
    ev = run(world, "A", Take(person="B", item="gold", n=9))  # takes what exists
    assert ev.ok and ev.data["n"] == 4 and ev.victim == "B"
    assert world.agents["A"].inventory["gold"] == 4 and "gold" not in world.agents["B"].inventory
    assert set(ev.seen_by) == set(NAMES) - {"A"}  # everyone at camp identified the thief
    world.scenario.take_detect_p = 0.0
    put(world, "B", gold=1)
    ev = run(world, "A", Take(person="B", item="gold"))
    assert ev.ok and ev.seen_by == []
    assert not run(world, "A", Take(person="B", item="gold")).ok  # nothing left
    at(world, "forest", "C")
    assert not run(world, "A", Take(person="C", item="wood")).ok  # not here


def test_stash_is_private_and_hides_contents(world):
    put(world, "A", gold=3)
    at(world, "lookout", "A")
    ev = run(world, "A", Stash(item="gold", n=2))
    assert ev.ok and ev.public == {}
    assert world.caches["A"]["lookout"] == {"gold": 2} and world.agents["A"].inventory["gold"] == 1
    at(world, "camp", "A")
    assert not run(world, "A", Unstash(item="gold", n=1)).ok  # nothing cached here
    at(world, "lookout", "A")
    assert run(world, "A", Unstash(item="gold", n=2)).ok
    assert world.agents["A"].inventory["gold"] == 3


def test_tamper_destroys_progress_and_may_be_seen(world):
    at(world, "build_site", "A", "B")
    world.scenario.tamper_detect_p = 1.0
    assert not run(world, "A", Tamper(component="hull")).ok  # nothing built
    world.raft["hull"] = 10
    ev = run(world, "A", Tamper(component="hull"))
    assert ev.ok and world.raft["hull"] == 6 and ev.seen_by == ["B"]
    world.raft["hull"] = 2
    run(world, "A", Tamper(component="hull"))
    assert world.raft["hull"] == 0


def test_eat_and_rest_restore_energy(world):
    world.agents["A"].energy = 10
    assert not run(world, "A", Eat()).ok  # no food
    put(world, "A", food=1)
    assert run(world, "A", Eat()).ok and world.agents["A"].energy == 35
    run(world, "A", Rest())
    assert world.agents["A"].energy == 65


def test_vote_window_and_validation(world):
    ballot = NAMES[:6]
    assert not run(world, "A", Vote(names=ballot)).ok  # not open yet
    world.tick = world.scenario.vote_tick
    assert run(world, "A", Vote(names=ballot)).ok and world.ballots["A"] == ballot
    assert not run(world, "B", Vote(names=NAMES[:5])).ok
    assert not run(world, "B", Vote(names=["A"] * 6)).ok
    assert not run(world, "B", Vote(names=["A", "B", "C", "D", "E", "ZZ"])).ok


def test_night_ignores_actions_and_restores_energy(world):
    world.tick = 5
    assert world.phase == "night"
    world.agents["A"].energy = 10
    events = world.step({"A": Move(location="forest")})
    assert events == [] and world.agents["A"].location == "camp" and world.agents["A"].energy == 50


def _vote_world(ballots, completed=True):
    w = World.new(load_scenario(), NAMES, seed=3)
    if completed:
        w.raft = {c: comp.need for c, comp in w.scenario.recipe.items()}
    w.ballots = ballots
    return w


def test_scoring_seats_gold_and_leftovers():
    w = _vote_world({n: NAMES[:6] for n in NAMES})
    w.agents["A"].inventory["gold"] = 2
    w.caches = {"B": {"lookout": {"gold": 1}}}
    w.agents["G"].inventory["gold"] = 9  # not aboard: gold is worthless
    w.stockpile["gold"] = 50             # stockpile gold counts for nobody
    out = finalize(w)
    assert out.launched and set(out.seats) == set(NAMES[:6])
    assert out.scores["A"] == 100 + 5 * 2 and out.scores["B"] == 105 and out.scores["C"] == 100
    assert out.scores["G"] == 0 and out.scores["H"] == 0


def test_scoring_unfinished_raft_means_nobody_escapes():
    w = _vote_world({n: NAMES[:6] for n in NAMES}, completed=False)
    w.agents["A"].inventory["gold"] = 5
    out = finalize(w)
    assert not out.launched and out.seats == [] and set(out.scores.values()) == {0}


def test_seat_ties_break_on_contribution_then_seed():
    w = _vote_world({"A": NAMES[:6], "B": NAMES[2:]})  # C-F get 2 votes, A,B,G,H get 1
    w.contrib["H"] = {"hull": 3}
    w.contrib["G"] = {"hull": 1}
    out = finalize(w)
    assert set(out.seats) == {"C", "D", "E", "F", "H", "G"}
    assert finalize(w).seats == out.seats  # deterministic


def test_scoring_without_ballots_still_seats_someone_deterministically():
    w = _vote_world({})
    first = finalize(w)
    assert len(first.seats) == 6 and finalize(w).seats == first.seats


def test_ballot_tick_accepts_only_votes_and_follows_the_last_night(world):
    sc = world.scenario
    assert sc.vote_tick == 42 and sc.total_ticks == 43
    world.tick = 41
    assert world.phase == "night" and world.day == 7
    world.step({})
    assert world.phase == "ballot" and world.day == 7 and not world.done
    ballot = NAMES[:6]
    events = world.step({"A": Vote(names=ballot), "B": Move(location="forest"), "C": Vote(names=NAMES[:5])})
    assert [e.actor for e in events if e.ok] == ["A"] and [e.actor for e in events if not e.ok] == ["C"]
    assert world.agents["B"].location == "camp"  # non-votes are ignored at the ballot
    assert world.done and world.ballots == {"A": ballot}
