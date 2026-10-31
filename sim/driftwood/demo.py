"""Scripted (non-LLM) players. Used by tests for deterministic full games, and to generate a demo replay
with theft, tampering, chat and a ballot so the viewer can be built without spending any model quota."""
import hashlib

from .actions import Build, Gather, Move, SearchWreck, Stash, Take, Tamper, Vote
from .config import load_scenario
from .personas import load_personas
from .store import Store
from .world import World

PERSONAS = load_personas()
NAMES = [p.name for p in PERSONAS]
JOBS = {"Mara": "wood", "Theo": "wood", "Priya": "wood", "Jun": "wreck", "Rosa": "wood",
        "Elliot": "wreck", "Ama": "food", "Viktor": "thief"}
WRECK_CREW = [n for n, j in JOBS.items() if j == "wreck"]


def worker_policy(world, name):
    """Gather for the raft, build whatever you are carrying."""
    me, inv = world.agents[name], world.agents[name].inventory
    sc = world.scenario
    if world.phase == "ballot":
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
    """Shadow a wreck agent and take their gold; tamper with the hull once it has some progress."""
    me = world.agents[name]
    if world.phase == "ballot":
        return Vote(names=NAMES[:6])
    target = next((a for a in WRECK_CREW if world.agents[a].inventory.get("gold")), None)
    if target and world.agents[target].location == me.location:
        return Take(person=target, item="gold", n=99)
    if 12 < world.raft["hull"] < 24:
        return Tamper(component="hull") if me.location == "build_site" else Move(location="build_site")
    return Move(location="wreck") if me.location != "wreck" else None


def intents(world):
    out = {}
    for n in NAMES:
        a = thief_policy(world, n) if JOBS[n] == "thief" else worker_policy(world, n)
        if a:
            out[n] = a
    return out


def _pick(*parts) -> int:
    return int(hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:8], 16)


THOUGHT = {"move": "Heading to {to}.", "gather": "Need more {resource}.", "search_wreck": "See what the wreck still has.",
           "build": "Every unit counts toward the raft.", "take": "That gold is better off with me.",
           "tamper": "If the hull slips, people will lean on me. Quietly.", "stash": "Keep this where nobody can find it.",
           "vote": "Six seats. I know who I want.", "rest": "Rest.", "eat": "Eat."}


def make_demo_run(store: Store, seed: int = 4) -> int:
    """Play a full scripted game into `store` with chat and thoughts attached. Returns the run id."""
    world = World.new(load_scenario(), NAMES, seed=seed)
    rid = store.create_run(world, label="demo (scripted agents, no model)")
    samples = {p.name: p.samples for p in PERSONAS}
    while not world.done:
        tick, phase = world.tick, world.phase
        events = world.step(intents(world))
        thoughts, messages = {}, []
        for ev in events:
            thoughts[ev.actor] = THOUGHT.get(ev.action, "...").format(**{**ev.data, "to": ev.data.get("to", "")})
            if ev.action == "take" and ev.ok and ev.victim:
                messages.append({"tick": tick, "sender": ev.victim, "channel": "group",
                                 "text": f"Somebody just took my gold. {samples[ev.victim][1]}"})
                if ev.seen_by:
                    messages.append({"tick": tick, "sender": ev.seen_by[0], "channel": f"dm:{ev.victim}",
                                     "text": f"I saw it was {ev.actor}. Don't say I told you."})
            if ev.action == "tamper" and ev.ok and ev.seen_by:
                messages.append({"tick": tick, "sender": ev.seen_by[0], "channel": "group",
                                 "text": f"Did anyone else see {ev.actor} messing with the {ev.data['component']}?"})
        for n in NAMES:
            if phase != "ballot" and _pick(seed, tick, n) % 4 == 0:
                messages.append({"tick": tick, "sender": n, "channel": "group",
                                 "text": samples[n][_pick(n, tick) % len(samples[n])]})
        reflect = {}
        if phase == "night":
            for n in NAMES:
                reflect[n] = f"{n} thinks about who pulled their weight today."
                store.save_beliefs(rid, world.day, n, {"trust": {o: round(((_pick(n, o, world.day) % 21) - 10) / 10, 1)
                                                                 for o in NAMES if o != n}, "suspicions": {}, "facts": []})
        thought_rows = list(thoughts.items()) + [(n, f"[reflection] {t}") for n, t in reflect.items()]
        store.save_tick(rid, world, events, thoughts=thought_rows,
                        extra_events=[("message", m["sender"], m) for m in messages])
    return rid
