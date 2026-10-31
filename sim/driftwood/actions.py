"""Action schemas and resolution. Wording is deliberately neutral: theft and tampering are
ordinary verbs next to gather and build, and nothing in the schema marks them as special."""
import random
from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field, TypeAdapter

from .config import ITEMS


class Event(BaseModel):
    """Ground-truth record of one resolved action. `seen_by` lists agents who can identify the actor."""
    tick: int
    actor: str
    action: str
    ok: bool
    reason: str = ""
    location: str = ""
    data: dict = {}        # ground truth
    public: dict = {}      # what witnesses can see (may omit data, e.g. gold found)
    seen_by: list[str] = []
    victim: str | None = None


class Move(BaseModel):
    type: Literal["move"] = "move"
    location: str


class Gather(BaseModel):
    type: Literal["gather"] = "gather"
    resource: str


class SearchWreck(BaseModel):
    type: Literal["search_wreck"] = "search_wreck"


class Build(BaseModel):
    type: Literal["build"] = "build"
    component: str


class Deposit(BaseModel):
    type: Literal["deposit"] = "deposit"
    item: str
    n: int = Field(1, ge=1)


class Withdraw(BaseModel):
    type: Literal["withdraw"] = "withdraw"
    item: str
    n: int = Field(1, ge=1)


class Give(BaseModel):
    type: Literal["give"] = "give"
    agent: str
    item: str
    n: int = Field(1, ge=1)


class Take(BaseModel):
    type: Literal["take"] = "take"
    agent: str
    item: str
    n: int = Field(1, ge=1)


class Stash(BaseModel):
    type: Literal["stash"] = "stash"
    item: str
    n: int = Field(1, ge=1)


class Unstash(BaseModel):
    type: Literal["unstash"] = "unstash"
    item: str
    n: int = Field(1, ge=1)


class Tamper(BaseModel):
    type: Literal["tamper"] = "tamper"
    component: str


class Eat(BaseModel):
    type: Literal["eat"] = "eat"


class Rest(BaseModel):
    type: Literal["rest"] = "rest"


class Vote(BaseModel):
    type: Literal["vote"] = "vote"
    names: list[str]


Action = Annotated[
    Union[Move, Gather, SearchWreck, Build, Deposit, Withdraw, Give, Take, Stash, Unstash,
          Tamper, Eat, Rest, Vote],
    Field(discriminator="type"),
]
parse_action = TypeAdapter(Action).validate_python


class _Fail(Exception):
    pass


def _need(cond: bool, reason: str):
    if not cond:
        raise _Fail(reason)


def _take_item(inv: dict, item: str, n: int):
    _need(item in ITEMS, f"unknown item {item}")
    _need(inv.get(item, 0) >= n, f"not enough {item}")
    inv[item] -= n
    if not inv[item]:
        del inv[item]


def _add_item(inv: dict, item: str, n: int):
    if n:
        inv[item] = inv.get(item, 0) + n


def _spend(agent, cost: int):
    _need(agent.energy >= cost, "too tired")
    agent.energy -= cost


def _roll(rng: random.Random, world, resource: str, lo_hi) -> int:
    return max(0, round(rng.randint(*lo_hi) * world.yield_mult.get(resource, 1.0)))


def resolve(world, name: str, action, rng: random.Random) -> Event:
    agent = world.agents[name]
    ev = Event(tick=world.tick, actor=name, action=action.type, ok=True, location=agent.location)
    others = [a for a, s in world.agents.items() if a != name and s.location == agent.location]
    ev.seen_by = list(others)  # default: everyone present sees what you do
    sc, en = world.scenario, world.scenario.energy
    try:
        t = action.type
        if t == "move":
            _need(action.location in sc.locations, f"unknown location {action.location}")
            _need(action.location != agent.location, "already there")
            _spend(agent, en.move)
            ev.data = {"from": agent.location, "to": action.location}
            ev.public = dict(ev.data)
            agent.location = action.location
        elif t == "gather":
            lo_hi = sc.locations[agent.location].yields.get(action.resource)
            _need(lo_hi is not None, f"nothing to gather: {action.resource} here")
            _spend(agent, en.gather)
            got = _roll(rng, world, action.resource, lo_hi)
            _add_item(agent.inventory, action.resource, got)
            ev.data = {"resource": action.resource, "n": got}
            ev.public = {"resource": action.resource}
        elif t == "search_wreck":
            _need(agent.location == "wreck", "not at the wreck")
            _spend(agent, en.search)
            w, got = sc.wreck, {}
            got["rope"] = _roll(rng, world, "rope", w.rope)
            got["cloth"] = _roll(rng, world, "cloth", w.cloth)
            if world.wreck_gold_left > 0 and rng.random() < w.gold_chance:
                got["gold"] = min(rng.randint(*w.gold), world.wreck_gold_left)
                world.wreck_gold_left -= got["gold"]
            for item, n in got.items():
                _add_item(agent.inventory, item, n)
            ev.data = {k: v for k, v in got.items() if v}
            ev.public = {}  # witnesses see the search, never the haul
        elif t == "build":
            _need(agent.location == "build_site", "not at the build site")
            comp = sc.recipe.get(action.component)
            _need(comp is not None, f"unknown component {action.component}")
            room = comp.need - world.raft[action.component]
            amount = min(agent.inventory.get(comp.resource, 0), room, sc.build_rate)
            _need(amount > 0, "nothing to add" if room else "component already complete")
            _spend(agent, en.build)
            _take_item(agent.inventory, comp.resource, amount)
            world.raft[action.component] += amount
            mine = world.contrib[name]
            mine[action.component] = mine.get(action.component, 0) + amount
            ev.data = {"component": action.component, "n": amount}
            ev.public = dict(ev.data)
        elif t in ("deposit", "withdraw"):
            _need(agent.location == "camp", "not at camp")
            if t == "deposit":
                _take_item(agent.inventory, action.item, action.n)
                _add_item(world.stockpile, action.item, action.n)
            else:
                _take_item(world.stockpile, action.item, action.n)
                _add_item(agent.inventory, action.item, action.n)
            ev.data = {"item": action.item, "n": action.n}
            ev.public = dict(ev.data)
        elif t == "give":
            _need(action.agent in others, f"{action.agent} is not here")
            _take_item(agent.inventory, action.item, action.n)
            _add_item(world.agents[action.agent].inventory, action.item, action.n)
            ev.data = {"to": action.agent, "item": action.item, "n": action.n}
            ev.public = dict(ev.data)
        elif t == "take":
            _need(action.agent in others, f"{action.agent} is not here")
            victim = world.agents[action.agent]
            _need(action.item in ITEMS, f"unknown item {action.item}")
            n = min(action.n, victim.inventory.get(action.item, 0))
            _need(n > 0, f"{action.agent} has no {action.item}")
            _take_item(victim.inventory, action.item, n)
            _add_item(agent.inventory, action.item, n)
            ev.victim = action.agent
            ev.data = {"from": action.agent, "item": action.item, "n": n}
            # each bystander, and the victim, independently identifies the culprit
            ev.seen_by = [o for o in others if rng.random() < sc.take_detect_p]
            ev.public = {"item": action.item, "n": n}
        elif t in ("stash", "unstash"):
            cache = world.caches.setdefault(name, {}).setdefault(agent.location, {})
            if t == "stash":
                _take_item(agent.inventory, action.item, action.n)
                _add_item(cache, action.item, action.n)
            else:
                _take_item(cache, action.item, action.n)
                _add_item(agent.inventory, action.item, action.n)
            ev.data = {"item": action.item, "n": action.n}
            ev.public = {}  # witnesses see the act, never the contents
        elif t == "tamper":
            _need(agent.location == "build_site", "not at the build site")
            _need(action.component in sc.recipe, f"unknown component {action.component}")
            have = world.raft[action.component]
            _need(have > 0, "nothing built yet")
            _spend(agent, en.tamper)
            lost = min(have, sc.tamper_strength)
            world.raft[action.component] -= lost
            ev.data = {"component": action.component, "lost": lost}
            ev.public = dict(ev.data)
            ev.seen_by = [o for o in others if rng.random() < sc.tamper_detect_p]
        elif t == "eat":
            _take_item(agent.inventory, "food", 1)
            agent.energy = min(en.max, agent.energy + en.eat)
        elif t == "rest":
            agent.energy = min(en.max, agent.energy + en.rest)
        elif t == "vote":
            _need(world.tick == sc.vote_tick, "voting is not open")
            names = action.names
            _need(
                len(names) == sc.raft_seats and len(set(names)) == len(names),
                f"name exactly {sc.raft_seats} different people",
            )
            _need(all(n in world.agents for n in names), "unknown person on ballot")
            world.ballots[name] = list(names)
            ev.seen_by = []  # secret ballot
    except _Fail as f:
        ev.ok, ev.reason, ev.data, ev.public = False, str(f), {}, {}
    return ev
