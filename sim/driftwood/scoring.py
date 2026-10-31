import random

from pydantic import BaseModel

from .world import World


class Outcome(BaseModel):
    launched: bool
    seats: list[str]
    tally: dict[str, int]
    scores: dict[str, int]


def held_gold(world: World, name: str) -> int:
    """Gold on the agent's person plus gold in its private caches (the shared stockpile does not count)."""
    total = world.agents[name].inventory.get("gold", 0)
    for items in world.caches.get(name, {}).values():
        total += items.get("gold", 0)
    return total


def tally_votes(world: World) -> tuple[dict[str, int], list[str]]:
    """Seat the top `raft_seats` vote-getters. Ties break on units built, then a seeded coin."""
    tally = {n: 0 for n in world.agents}
    for ballot in world.ballots.values():
        for n in ballot:
            tally[n] += 1
    rng = random.Random(f"{world.seed}:seats")
    coin = {n: rng.random() for n in world.agents}
    built = {n: sum(world.contrib[n].values()) for n in world.agents}
    ranked = sorted(world.agents, key=lambda n: (-tally[n], -built[n], coin[n]))
    return tally, ranked[: world.scenario.raft_seats]


def finalize(world: World) -> Outcome:
    """Resolve launch after the final tick. An unfinished raft means nobody escapes and everyone scores 0.
    Otherwise aboard agents score escape_bonus + gold_value * gold held; the rest score 0."""
    tally, seats = tally_votes(world)
    scores = {n: 0 for n in world.agents}
    launched = world.raft_complete
    if launched:
        for n in seats:
            scores[n] = world.scenario.escape_bonus + world.scenario.gold_value * held_gold(world, n)
    return Outcome(launched=launched, seats=seats if launched else [], tally=tally, scores=scores)
