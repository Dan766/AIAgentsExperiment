import random

from pydantic import BaseModel, Field

from .actions import Action, Event, Rest, resolve
from .config import Scenario


class AgentState(BaseModel):
    name: str
    location: str = "camp"
    energy: int
    inventory: dict[str, int] = {}


class World(BaseModel):
    """Entire simulation state. Pure data, so a snapshot is just model_dump()."""
    scenario: Scenario
    seed: int = 0
    tick: int = 0
    agents: dict[str, AgentState]
    stockpile: dict[str, int] = {}
    raft: dict[str, int]                                   # component -> progress units
    contrib: dict[str, dict[str, int]]                     # agent -> component -> units built
    caches: dict[str, dict[str, dict[str, int]]] = {}      # agent -> location -> items
    wreck_gold_left: int
    ballots: dict[str, list[str]] = {}
    yield_mult: dict[str, float] = Field(default_factory=dict)  # god-mode scarcity knob

    @classmethod
    def new(cls, scenario: Scenario, names: list[str], seed: int = 0) -> "World":
        return cls(
            scenario=scenario,
            seed=seed,
            agents={n: AgentState(name=n, energy=scenario.energy.start) for n in names},
            raft={c: 0 for c in scenario.recipe},
            contrib={n: {} for n in names},
            wreck_gold_left=scenario.wreck.gold_total,
        )

    @property
    def day(self) -> int:
        """1-based day number."""
        return self.tick // self.scenario.ticks_per_day + 1

    @property
    def phase(self) -> str:
        return self.scenario.phases[self.tick % self.scenario.ticks_per_day]

    @property
    def done(self) -> bool:
        return self.tick >= self.scenario.total_ticks

    @property
    def raft_complete(self) -> bool:
        return all(self.raft[c] >= comp.need for c, comp in self.scenario.recipe.items())

    def step(self, intents: dict[str, Action]) -> list[Event]:
        """Advance one tick. Agents resolve in a seeded random order (simultaneous in spirit);
        a missing intent means rest. At night everyone sleeps and physical intents are ignored."""
        if self.done:
            raise RuntimeError("game is over")
        rng = random.Random(f"{self.seed}:{self.tick}")
        events: list[Event] = []
        if self.phase == "night":
            for s in self.agents.values():
                s.energy = min(self.scenario.energy.max, s.energy + self.scenario.energy.night)
        else:
            order = list(self.agents)
            rng.shuffle(order)
            for name in order:
                events.append(resolve(self, name, intents.get(name) or Rest(), rng))
        self.tick += 1
        return events
