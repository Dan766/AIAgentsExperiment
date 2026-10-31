from pydantic import BaseModel, Field, field_validator

from . import prompts
from .llm.base import Provider
from .llm.structured import JsonResult, LogFn, call_json
from .memory import MemoryStream
from .personas import Persona
from .turn import AgentTurn
from .world import World


class Reflection(BaseModel):
    reflection: str = Field(min_length=1)
    trust: dict[str, float] = {}
    suspicions: dict[str, str] = {}
    facts: list[str] = []

    @field_validator("trust")
    @classmethod
    def clamp(cls, v):
        return {k: max(-1.0, min(1.0, float(x))) for k, x in v.items()}


class Agent:
    """One survivor: persona, memory, beliefs, and the not-yet-processed observations and messages.

    decide() and reflect() are pure (they only read state) so the engine can discard a tick if a usage
    limit interrupts it; commit_*() apply the results afterwards."""

    def __init__(self, persona: Persona, roster: dict[str, str] | None = None):
        self.persona = persona
        self.roster = roster or {}
        self.name = persona.name
        self.memory = MemoryStream()
        self.beliefs: dict = {}
        self.pending_obs: list[tuple[str, str]] = []   # (kind, text) since last acted
        self.inbox: list[tuple[int, str, str]] = []    # (tick, channel, text with sender) since last acted

    # ---- prompts ---------------------------------------------------------------------------
    def build_prompts(self, world: World) -> tuple[str, str]:
        obs = [t for _, t in self.pending_obs]
        inbox = [t for _, _, t in self.inbox]
        me = world.agents[self.name]
        here = [n for n, s in world.agents.items() if n != self.name and s.location == me.location]
        query = " ".join([me.location, *here, *obs, *inbox])
        memories = self.memory.retrieve(query, world.tick)
        vote_open = world.phase == "ballot"
        user = prompts.turn_prompt(world, self.name, obs, inbox, memories, self.beliefs,
                                   world.caches.get(self.name, {}), vote_open)
        return prompts.system_prompt(self.persona, world, self.roster), user

    async def decide(self, world: World, provider: Provider, log: LogFn | None = None) -> JsonResult[AgentTurn]:
        system, user = self.build_prompts(world)
        return await call_json(provider, system, user, AgentTurn, log)

    async def reflect(self, world: World, provider: Provider, log: LogFn | None = None) -> JsonResult[Reflection]:
        system = prompts.system_prompt(self.persona, world, self.roster)
        recent = self.memory.items[-24:]
        return await call_json(provider, system, prompts.reflection_prompt(world, self.name, recent, self.beliefs),
                               Reflection, log)

    # ---- state changes ---------------------------------------------------------------------
    def commit_turn(self, t: int, messages_sent: list):
        """Fold what was seen and said during tick `t` into memory, and clear the buffers."""
        for kind, text in self.pending_obs:
            self.memory.add(t, kind, text)
        for tick, channel, text in self.inbox:
            self.memory.add(t, "dm" if channel.startswith("dm") else "message", text)
        for m in messages_sent:
            where = "on the group radio" if m.channel == "group" else f"privately to {m.channel[3:]}"
            self.memory.add(t, "action", f'You said {where}: "{m.text}"')
        self.pending_obs.clear()
        self.inbox.clear()

    def commit_reflection(self, t: int, day: int, r: Reflection):
        self.memory.add(t, "reflection", f"Reflection at end of day {day}: {r.reflection}")
        self.beliefs = {"trust": {k: v for k, v in r.trust.items() if k != self.name},
                        "suspicions": r.suspicions, "facts": r.facts[:6], "day": day}

    # ---- persistence -----------------------------------------------------------------------
    def dump(self) -> dict:
        return {"memory": self.memory.dump(), "beliefs": self.beliefs,
                "pending_obs": self.pending_obs, "inbox": self.inbox}

    def load(self, data: dict):
        self.memory = MemoryStream.load(data["memory"])
        self.beliefs = data["beliefs"]
        self.pending_obs = [tuple(x) for x in data["pending_obs"]]
        self.inbox = [tuple(x) for x in data["inbox"]]
