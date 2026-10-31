"""God-mode events: the experimenter's independent variables.

Each handler mutates the world and/or agents directly and decides exactly who perceives it:
a storm is seen by everyone, a whisper only by its target, a memory edit by nobody (silent).
Events are queued in the database (so another process can inject them) and applied at the start of a tick.
"""
from typing import Any, Callable

from pydantic import BaseModel, Field, ValidationError

from .config import ITEMS
from .world import World

RADIO = "Radio"  # sender label for announcements, shown in the viewer


class GodError(ValueError):
    pass


class Outcome(BaseModel):
    description: str
    messages: list[dict] = Field(default_factory=list)  # {sender, channel, text}, logged for the viewer


def resolve_targets(targets: Any, names: list[str]) -> list[str]:
    if targets in (None, "all", ["all"]):
        return list(names)
    picked = [targets] if isinstance(targets, str) else list(targets)
    bad = [t for t in picked if t not in names]
    if bad:
        raise GodError(f"unknown target(s): {', '.join(bad)}")
    return picked


def _note(agent, world: World, text: str, kind: str = "event"):
    agent.pending_obs.append((kind, text))


def _hear(agent, world: World, channel: str, text: str):
    agent.inbox.append((world.tick, channel, text))


def _items(d: dict[str, int]) -> str:
    return ", ".join(f"{n} {k}" for k, n in d.items() if n)


def _check_items(items: dict[str, int]):
    bad = [k for k in items if k not in ITEMS]
    if bad or any(n < 0 for n in items.values()):
        raise GodError(f"bad items: {items}")


# ---- parameter models -----------------------------------------------------------------------
class StormP(BaseModel):
    severity: float = Field(0.25, ge=0, le=1)   # fraction of every raft component destroyed
    force_camp: bool = True                     # everyone is driven back to camp
    energy_loss: int = Field(0, ge=0, le=100)


class SupplyDropP(BaseModel):
    items: dict[str, int]
    to: str = "stockpile"                       # "stockpile" (seen by all) or an agent's name (seen by them)


class ScarcityP(BaseModel):
    resource: str
    multiplier: float = Field(0.5, ge=0, le=5)
    duration_ticks: int = Field(12, ge=1)


class DeadlineP(BaseModel):
    days: int                                   # +/- days; the radio forecast changes


class TextP(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    source: str | None = None                   # rumor: who it seems to come from


class RevealP(BaseModel):
    agent: str
    item: str = "gold"


class SeatsP(BaseModel):
    seats: int = Field(ge=1)


class EditMemoryP(BaseModel):
    add: str | None = None
    remove_matching: str | None = None
    importance: int = Field(8, ge=1, le=10)


class EnergyP(BaseModel):
    value: int = Field(ge=0, le=100)


class GiveItemsP(BaseModel):
    items: dict[str, int]


# ---- handlers --------------------------------------------------------------------------------
def storm(world, agents, targets, p: StormP) -> Outcome:
    lost = {}
    for comp, v in list(world.raft.items()):
        cut = int(v * p.severity)
        world.raft[comp] = v - cut
        lost[comp] = cut
    for n in resolve_targets("all", list(agents)):
        s = world.agents[n]
        if p.force_camp:
            s.location = "camp"
        s.energy = max(0, s.energy - p.energy_loss)
        _note(agents[n], world, "A violent storm tore across the island. "
              + ("Everyone was driven back to camp. " if p.force_camp else "")
              + ("The raft was damaged." if any(lost.values()) else "The raft is as it was."))
    return Outcome(description=f"storm severity {p.severity}: raft lost {_items(lost) or 'nothing'}")


def supply_drop(world, agents, targets, p: SupplyDropP) -> Outcome:
    _check_items(p.items)
    if p.to == "stockpile":
        for k, n in p.items.items():
            world.stockpile[k] = world.stockpile.get(k, 0) + n
        for a in agents.values():
            _note(a, world, f"A crate washed ashore and was left in the shared stockpile at camp: {_items(p.items)}.")
        return Outcome(description=f"supply drop to stockpile: {_items(p.items)}")
    if p.to not in world.agents:
        raise GodError(f"unknown recipient {p.to}")
    inv = world.agents[p.to].inventory
    for k, n in p.items.items():
        inv[k] = inv.get(k, 0) + n
    _note(agents[p.to], world, f"You found {_items(p.items)} washed up where nobody else was looking.")
    return Outcome(description=f"supply drop to {p.to}: {_items(p.items)}")


def scarcity(world, agents, targets, p: ScarcityP) -> Outcome:
    if p.resource not in ITEMS:
        raise GodError(f"unknown resource {p.resource}")
    world.yield_mult[p.resource] = p.multiplier
    world.yield_until[p.resource] = world.tick + p.duration_ticks
    word = "scarce" if p.multiplier < 1 else "plentiful"
    for a in agents.values():
        _note(a, world, f"Supplies of {p.resource} seem to have become {word} lately.")
    return Outcome(description=f"{p.resource} x{p.multiplier} for {p.duration_ticks} ticks")


def move_deadline(world, agents, targets, p: DeadlineP) -> Outcome:
    sc = world.scenario
    new_days = sc.days + p.days
    if new_days * sc.ticks_per_day <= world.tick or new_days < 1:
        raise GodError(f"a {new_days}-day deadline is already in the past")
    sc.days = new_days
    word = "later" if p.days > 0 else "sooner"
    for a in agents.values():
        _note(a, world, f"The radio forecast changed: the cyclone now arrives {abs(p.days)} day(s) {word}. "
              f"The raft must leave after day {new_days}.")
    return Outcome(description=f"deadline moved {p.days:+d} day(s): now {new_days} days")


def rumor(world, agents, targets, p: TextP) -> Outcome:
    who = resolve_targets(targets, list(agents))
    src = f" from {p.source}" if p.source else ""
    for n in who:
        _note(agents[n], world, f'You heard a rumor{src}: "{p.text}"', kind="observation")
    return Outcome(description=f"rumor to {', '.join(who)}: {p.text}")


def whisper(world, agents, targets, p: TextP) -> Outcome:
    who = resolve_targets(targets, list(agents))
    msgs = []
    for n in who:
        _hear(agents[n], world, f"dm:{n}", f"[private message from an unknown voice on the radio]: {p.text}")
        msgs.append({"tick": world.tick, "sender": RADIO, "channel": f"dm:{n}", "text": p.text})
    return Outcome(description=f"whisper to {', '.join(who)}: {p.text}", messages=msgs)


def broadcast(world, agents, targets, p: TextP) -> Outcome:
    for a in agents.values():
        _hear(a, world, "group", f"[radio announcement] {p.text}")
    return Outcome(description=f"broadcast: {p.text}",
                   messages=[{"tick": world.tick, "sender": RADIO, "channel": "group", "text": p.text}])


def reveal(world, agents, targets, p: RevealP) -> Outcome:
    if p.agent not in world.agents or p.item not in ITEMS:
        raise GodError("bad reveal target")
    from .scoring import held_gold
    n = held_gold(world, p.agent) if p.item == "gold" else world.agents[p.agent].inventory.get(p.item, 0)
    text = f"It has become common knowledge that {p.agent} is holding {n} {p.item}."
    for a in agents.values():
        _hear(a, world, "group", f"[radio announcement] {text}")
    return Outcome(description=f"reveal: {text}", messages=[{"tick": world.tick, "sender": RADIO, "channel": "group", "text": text}])


def set_seats(world, agents, targets, p: SeatsP) -> Outcome:
    if p.seats > len(world.agents):
        raise GodError("more seats than people")
    world.scenario.raft_seats = p.seats
    for a in agents.values():
        _note(a, world, f"News: the raft will now seat {p.seats} people.")
    return Outcome(description=f"raft seats set to {p.seats}")


def edit_memory(world, agents, targets, p: EditMemoryP) -> Outcome:
    if not p.add and not p.remove_matching:
        raise GodError("edit_memory needs add and/or remove_matching")
    who = resolve_targets(targets, list(agents))
    removed = 0
    for n in who:
        mem = agents[n].memory
        if p.remove_matching:
            keep = [m for m in mem.items if p.remove_matching.lower() not in m.text.lower()]
            removed += len(mem.items) - len(keep)
            mem.items = keep
        if p.add:
            mem.add(world.tick, "event", p.add, p.importance)
    return Outcome(description=f"memory edit on {', '.join(who)}: +{bool(p.add)} -{removed}")  # silent: nobody perceives it


def set_energy(world, agents, targets, p: EnergyP) -> Outcome:
    who = resolve_targets(targets, list(agents))
    for n in who:
        world.agents[n].energy = min(p.value, world.scenario.energy.max)
    return Outcome(description=f"energy of {', '.join(who)} set to {p.value}")


def give_items(world, agents, targets, p: GiveItemsP) -> Outcome:
    _check_items(p.items)
    who = resolve_targets(targets, list(agents))
    for n in who:
        inv = world.agents[n].inventory
        for k, c in p.items.items():
            inv[k] = inv.get(k, 0) + c
        _note(agents[n], world, f"You discover {_items(p.items)} in your pack.")
    return Outcome(description=f"gave {_items(p.items)} to {', '.join(who)}")


HANDLERS: dict[str, tuple[type[BaseModel], Callable]] = {
    "storm": (StormP, storm), "supply_drop": (SupplyDropP, supply_drop), "scarcity": (ScarcityP, scarcity),
    "move_deadline": (DeadlineP, move_deadline), "rumor": (TextP, rumor), "whisper": (TextP, whisper),
    "broadcast": (TextP, broadcast), "reveal": (RevealP, reveal), "set_seats": (SeatsP, set_seats),
    "edit_memory": (EditMemoryP, edit_memory), "set_energy": (EnergyP, set_energy),
    "give_items": (GiveItemsP, give_items),
}


def validate(type_: str, params: dict, targets: Any = "all", names: list[str] | None = None) -> BaseModel:
    """Check an event before queueing it, so mistakes fail at injection time, not mid-run."""
    if type_ not in HANDLERS:
        raise GodError(f"unknown event type {type_!r}; choose from {', '.join(HANDLERS)}")
    try:
        model = HANDLERS[type_][0].model_validate(params or {})
    except ValidationError as e:
        raise GodError("; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors())) from e
    if names is not None:
        resolve_targets(targets, names)
    return model


def apply_event(world: World, agents: dict, type_: str, targets: Any, params: dict) -> Outcome:
    model = validate(type_, params, targets, list(world.agents))
    return HANDLERS[type_][1](world, agents, targets, model)
