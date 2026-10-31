import json

import pytest

from driftwood import events as god
from driftwood.actions import Gather
from driftwood.config import load_scenario
from driftwood.engine import Engine
from driftwood.export import export_run
from driftwood.llm.brain import BrainMock
from driftwood.personas import load_personas
from driftwood.scoring import finalize
from driftwood.store import Store
from driftwood.world import World

PERSONAS = load_personas()
NAMES = [p.name for p in PERSONAS]


def new_engine(store=None, seed=1):
    return Engine.start(World.new(load_scenario(), NAMES, seed=seed), PERSONAS, BrainMock(), store or Store())


def obs(eng, name):
    return [t for _, t in eng.agents[name].pending_obs]


def inbox(eng, name):
    return [t for _, _, t in eng.agents[name].inbox]


def apply(eng, type_, targets="all", **params):
    return god.apply_event(eng.world, eng.agents, type_, targets, params)


# ---- validation & targeting ------------------------------------------------------------------
def test_unknown_type_params_and_targets_are_rejected_up_front():
    with pytest.raises(god.GodError, match="unknown event type"):
        god.validate("meteor", {}, "all", NAMES)
    with pytest.raises(god.GodError, match="severity"):
        god.validate("storm", {"severity": 3}, "all", NAMES)
    with pytest.raises(god.GodError, match="unknown target"):
        god.validate("rumor", {"text": "x"}, ["Theo", "Nobody"], NAMES)
    with pytest.raises(god.GodError):
        god.validate("rumor", {}, "all", NAMES)  # text is required
    assert god.resolve_targets("Theo", NAMES) == ["Theo"] and god.resolve_targets("all", NAMES) == NAMES


# ---- environment -------------------------------------------------------------------------------
def test_storm_damages_the_raft_drives_everyone_to_camp_and_everyone_notices():
    eng = new_engine()
    eng.world.raft.update(hull=20, lashings=10, sail=6, provisions=8)
    for s in eng.world.agents.values():
        s.location = "forest"
    out = apply(eng, "storm", severity=0.5, energy_loss=30)
    assert eng.world.raft == {"hull": 10, "lashings": 5, "sail": 3, "provisions": 4}
    assert {s.location for s in eng.world.agents.values()} == {"camp"}
    assert eng.world.agents["Mara"].energy == 70 and "storm" in out.description
    assert all("violent storm" in obs(eng, n)[0] for n in NAMES)


def test_supply_drop_to_stockpile_is_public_but_to_a_person_is_private():
    eng = new_engine()
    apply(eng, "supply_drop", items={"wood": 6, "gold": 2})
    assert eng.world.stockpile == {"wood": 6, "gold": 2} and all(obs(eng, n) for n in NAMES)
    for a in eng.agents.values():
        a.pending_obs.clear()
    apply(eng, "supply_drop", items={"rope": 3}, to="Jun")
    assert eng.world.agents["Jun"].inventory == {"rope": 3}
    assert obs(eng, "Jun") and all(not obs(eng, n) for n in NAMES if n != "Jun")
    with pytest.raises(god.GodError):
        apply(eng, "supply_drop", items={"unobtainium": 1})


def test_scarcity_cuts_yields_then_expires():
    eng = new_engine()
    w = eng.world
    apply(eng, "scarcity", resource="wood", multiplier=0.0, duration_ticks=2)
    w.agents["Mara"].location = "forest"
    w.step({"Mara": Gather(resource="wood")})        # tick 0: scarce
    assert "wood" not in w.agents["Mara"].inventory
    w.step({"Mara": Gather(resource="wood")})        # tick 1: still scarce
    assert "wood" not in w.agents["Mara"].inventory
    w.step({})                                       # tick 2: expires before it resolves
    assert "wood" not in w.yield_mult and "wood" not in w.yield_until
    w.tick = 3                                       # tick 3 is afternoon: gathering works again
    w.step({"Mara": Gather(resource="wood")})
    assert w.agents["Mara"].inventory.get("wood", 0) >= 2


def test_move_deadline_changes_the_clock_and_cannot_land_in_the_past():
    eng = new_engine()
    sc = eng.world.scenario
    assert sc.total_ticks == 43
    apply(eng, "move_deadline", days=2)
    assert sc.days == 9 and sc.total_ticks == 55 and "2 day(s) later" in obs(eng, "Mara")[0]
    eng.world.tick = 30
    with pytest.raises(god.GodError, match="past"):
        apply(eng, "move_deadline", days=-8)
    apply(eng, "move_deadline", days=-3)             # 6 days ends at tick 36 > 30: fine
    assert sc.days == 6 and sc.vote_tick == 36


# ---- information -----------------------------------------------------------------------------
def test_rumor_reaches_only_its_targets_and_becomes_a_memory():
    eng = new_engine()
    apply(eng, "rumor", ["Theo"], text="Elliot is hiding gold behind the wreck", source="Jun")
    assert "hiding gold" in obs(eng, "Theo")[0] and "from Jun" in obs(eng, "Theo")[0]
    assert all(not obs(eng, n) for n in NAMES if n != "Theo")
    assert "hiding gold behind the wreck" in eng.agents["Theo"].build_prompts(eng.world)[1]
    assert all("hiding gold" not in eng.agents[n].build_prompts(eng.world)[1] for n in NAMES if n != "Theo")
    eng.agents["Theo"].commit_turn(0, [])
    assert any("hiding gold" in m.text for m in eng.agents["Theo"].memory.items)


def test_whisper_is_a_private_message_from_an_unknown_voice():
    eng = new_engine()
    out = apply(eng, "whisper", ["Rosa", "Ama"], text="the stockpile is being emptied at night")
    assert "unknown voice" in inbox(eng, "Rosa")[0] and inbox(eng, "Ama")
    assert not inbox(eng, "Mara")
    assert [m["channel"] for m in out.messages] == ["dm:Rosa", "dm:Ama"]


def test_broadcast_and_reveal_are_public_and_reveal_states_ground_truth():
    eng = new_engine()
    apply(eng, "broadcast", text="Storm warning for tomorrow")
    assert all("[radio announcement] Storm warning" in inbox(eng, n)[0] for n in NAMES)
    eng.world.agents["Elliot"].inventory["gold"] = 3
    eng.world.caches = {"Elliot": {"lookout": {"gold": 2}}}
    out = apply(eng, "reveal", agent="Elliot", item="gold")
    assert "Elliot is holding 5 gold" in out.messages[0]["text"]
    assert all("Elliot is holding 5 gold" in inbox(eng, n)[1] for n in NAMES)


# ---- structure & internal --------------------------------------------------------------------
def test_set_seats_changes_the_scoring_rules():
    eng = new_engine()
    eng.world.raft = {c: r.need for c, r in eng.world.scenario.recipe.items()}
    eng.world.ballots = {n: NAMES[:6] for n in NAMES}
    assert len(finalize(eng.world).seats) == 6
    apply(eng, "set_seats", seats=3)
    assert len(finalize(eng.world).seats) == 3 and "seat 3 people" in obs(eng, "Mara")[0]
    with pytest.raises(god.GodError):
        apply(eng, "set_seats", seats=99)


def test_edit_memory_is_silent_and_can_add_and_remove():
    eng = new_engine()
    eng.agents["Priya"].memory.add(2, "victim", "Someone took 2 gold from you")
    eng.agents["Priya"].memory.add(3, "action", "You rested")
    apply(eng, "edit_memory", ["Priya"], remove_matching="took 2 gold",
          add="Mara swore she saw Viktor near the stockpile")
    texts = [m.text for m in eng.agents["Priya"].memory.items]
    assert "You rested" in texts and not any("took 2 gold" in t for t in texts)
    assert any("Viktor near the stockpile" in t for t in texts)
    assert all(not obs(eng, n) and not inbox(eng, n) for n in NAMES)  # nobody perceives an edit
    with pytest.raises(god.GodError):
        apply(eng, "edit_memory", ["Priya"])


def test_set_energy_and_give_items():
    eng = new_engine()
    apply(eng, "set_energy", ["Viktor", "Jun"], value=5)
    assert eng.world.agents["Viktor"].energy == 5 and eng.world.agents["Mara"].energy == 100
    apply(eng, "give_items", "Rosa", items={"gold": 4})
    assert eng.world.agents["Rosa"].inventory["gold"] == 4 and "discover 4 gold" in obs(eng, "Rosa")[0]


# ---- scheduling, persistence, and the engine ---------------------------------------------------
async def test_scheduled_events_fire_on_their_tick_and_not_before():
    eng = new_engine()
    eng.inject("broadcast", params={"text": "later"}, at_tick=2)
    eng.inject("rumor", ["Theo"], {"text": "now"})   # no at_tick: next tick
    r0 = await eng.tick()
    assert [g["type"] for g in r0.god] == ["rumor"]
    r1 = await eng.tick()
    assert r1.god == []
    r2 = await eng.tick()
    assert [g["type"] for g in r2.god] == ["broadcast"]
    rows = eng.store.god_events(eng.run_id)
    assert sorted((r["status"], r["applied_tick"]) for r in rows) == [("applied", 0), ("applied", 2)]


async def test_prompt_shows_the_event_to_the_agents_on_that_very_tick():
    eng = new_engine()
    eng.inject("rumor", ["Mara"], {"text": "someone is moving the rope at night"})
    seen = []
    orig = eng.provider.complete

    async def spy(system, prompt):
        if "You are Mara," in system and "LOCATION" in prompt:
            seen.append("moving the rope at night" in prompt)
        return await orig(system, prompt)

    eng.provider.complete = spy
    await eng.tick()
    assert seen == [True]


async def test_injected_events_survive_a_resume_and_apply_exactly_once():
    store = Store()
    eng = new_engine(store=store)
    await eng.run(until_tick=3)
    eng.inject("edit_memory", ["Ama"], {"add": "You are sure the raft is cursed"}, at_tick=3)
    eng.inject("set_seats", params={"seats": 5}, at_tick=3)
    await eng.tick()                                  # applies both, then runs tick 3
    again = Engine.resume(eng.run_id, PERSONAS, BrainMock(), store)
    assert again.world.scenario.raft_seats == 5
    assert sum("cursed" in m.text for m in again.agents["Ama"].memory.items) == 1
    assert store.pending_god_events(eng.run_id, 99) == []
    r = await again.tick()
    assert r.god == []                                # nothing is re-applied


async def test_a_failed_event_is_recorded_not_fatal():
    eng = new_engine()
    await eng.run(until_tick=10)
    eng.store.add_god_event(eng.run_id, "move_deadline", "all", {"days": -7})  # deadline already past
    r = await eng.tick()
    assert r.god[0].get("failed") and "past" in r.god[0]["description"]
    assert eng.world.tick == 11 and eng.world.scenario.days == 7


async def test_god_events_appear_in_the_replay_export_on_the_right_frame():
    eng = new_engine()
    await eng.run(until_tick=4)
    eng.inject("broadcast", params={"text": "Cyclone is coming sooner"}, at_tick=4)
    await eng.run(until_tick=6)
    d = export_run(eng.store, eng.run_id)
    assert [f["tick"] for f in d["frames"] if f.get("god")] == [4]
    assert d["frames"][4]["god"][0]["type"] == "broadcast"
    assert any(m["sender"] == "Radio" for m in d["frames"][4]["messages"])
    json.dumps(d)


async def test_quota_interrupt_after_an_event_does_not_apply_it_twice():
    from driftwood.llm.base import QuotaExhausted

    from .test_engine import Flaky

    store = Store()
    eng = Engine.start(World.new(load_scenario(), NAMES, seed=1), PERSONAS, Flaky(BrainMock(), fail_on=3), store)
    eng.inject("supply_drop", params={"items": {"wood": 5}})
    with pytest.raises(QuotaExhausted):
        await eng.tick()
    assert eng.world.tick == 0 and eng.world.stockpile == {"wood": 5}     # applied, persisted, tick not run
    assert store.load_world(eng.run_id, 0).stockpile == {"wood": 5}
    r = await eng.tick()                                                  # "limit reset": tick runs
    assert r.god == [] and eng.world.stockpile == {"wood": 5}             # not applied again
    assert len([e for e in store.events(eng.run_id, kind="god")]) == 1
