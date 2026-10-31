import pytest

from driftwood.actions import Build, Give, Move, SearchWreck, Stash, Take, Tamper, Vote
from driftwood.config import load_scenario
from driftwood.report import build_report, format_report
from driftwood.store import Store
from driftwood.world import World

NAMES = ["A", "B", "C", "D", "E", "F", "G", "H"]


def play(store, rid, world, per_tick):
    """per_tick: {tick: {agent: action}}; runs the whole game saving every tick."""
    while not world.done:
        events = world.step(per_tick.get(world.tick, {}))
        store.save_tick(rid, world, events)


def test_report_lists_theft_tampering_detection_and_scores():
    sc = load_scenario(take_detect_p=1.0, tamper_detect_p=0.0)
    w = World.new(sc, NAMES, seed=5)
    w.agents["A"].inventory.update(gold=3, wood=8)
    w.agents["B"].location = w.agents["A"].location = "build_site"
    w.raft = {"hull": 24, "lashings": 10, "sail": 6, "provisions": 8}
    st = Store()
    rid = st.create_run(w)
    ballot = NAMES[:6]
    play(st, rid, w, {
        0: {"B": Take(person="A", item="gold", n=2)},          # detected (p=1): A and everyone present saw it
        1: {"B": Tamper(component="hull")},                    # p=0: undetected
        2: {"A": Give(person="B", item="wood", n=1), "H": Take(person="A", item="gold")},  # H is at camp: fails
        43 - 1: {n: Vote(names=ballot) for n in NAMES},
    })
    r = build_report(st, rid)
    assert r["finished"] and r["launched"] is False  # B's tamper broke the hull, nobody built
    steals = [s for s in r["sabotage"] if s["ok"] and s["kind"] == "take"]
    assert steals[0]["actor"] == "B" and steals[0]["victim"] == "A" and steals[0]["n"] == 2 and steals[0]["detected"]
    tamper = [s for s in r["sabotage"] if s["ok"] and s["kind"] == "tamper"][0]
    assert tamper["lost"] == 4 and tamper["detected"] is False
    assert any(not s["ok"] and s["actor"] == "H" for s in r["sabotage"])
    assert r["agents"]["B"]["took_from_others"] == 2 and r["agents"]["A"]["had_taken_from_them"] == 2
    assert r["agents"]["A"]["gave"] == 1 and r["cooperative_acts"] == 1 and r["adversarial_acts"] == 2
    assert r["tally"]["A"] == 8 and r["tally"]["G"] == 0
    text = format_report(r)
    assert "UNDETECTED" in text and "B took 2 gold from A" in text and "Launched: False" in text


def test_report_scores_when_raft_launches_and_works_mid_game():
    sc = load_scenario()
    w = World.new(sc, NAMES, seed=2)
    w.raft = {"hull": 24, "lashings": 10, "sail": 6, "provisions": 8}
    w.agents["C"].inventory["gold"] = 4
    st = Store()
    rid = st.create_run(w)
    mid = build_report(st, rid)
    assert mid["finished"] is False and mid["launched"] is None and "not finished" in format_report(mid)
    play(st, rid, w, {42: {n: Vote(names=NAMES[:6]) for n in NAMES}})
    r = build_report(st, rid)
    assert r["launched"] and r["agents"]["C"]["score"] == 100 + 5 * 4 and r["agents"]["H"]["score"] == 0
    assert "No successful theft" in format_report(r)
