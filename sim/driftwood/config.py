from pathlib import Path

import yaml
from pydantic import BaseModel

ITEMS = ("wood", "rope", "cloth", "food", "gold")
DATA_DIR = Path(__file__).parent / "data"


class Energy(BaseModel):
    start: int
    max: int
    move: int
    gather: int
    search: int
    build: int
    tamper: int
    rest: int
    eat: int
    night: int


class Component(BaseModel):
    resource: str
    need: int


class Wreck(BaseModel):
    rope: tuple[int, int]
    cloth: tuple[int, int]
    gold_chance: float
    gold: tuple[int, int]
    gold_total: int


class Location(BaseModel):
    yields: dict[str, tuple[int, int]] = {}


class Scenario(BaseModel):
    days: int
    phases: list[str]
    raft_seats: int
    escape_bonus: int
    gold_value: int
    vote_phase: str
    take_detect_p: float
    tamper_detect_p: float
    tamper_strength: int
    build_rate: int
    energy: Energy
    recipe: dict[str, Component]
    wreck: Wreck
    locations: dict[str, Location]

    @property
    def ticks_per_day(self) -> int:
        return len(self.phases)

    @property
    def total_ticks(self) -> int:
        return self.days * self.ticks_per_day

    @property
    def vote_tick(self) -> int:
        return (self.days - 1) * self.ticks_per_day + self.phases.index(self.vote_phase)


def load_scenario(path: Path | None = None, **overrides) -> Scenario:
    data = yaml.safe_load((path or DATA_DIR / "scenario.yaml").read_text(encoding="utf-8"))
    data.update(overrides)
    return Scenario.model_validate(data)
