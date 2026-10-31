import asyncio
from dataclasses import dataclass, field

from .actions import Event, Rest
from .agents import Agent, Reflection
from .llm.base import LLMResponse, Provider, QuotaExhausted
from .llm.structured import JsonResult
from .perception import observe
from .personas import Persona
from .store import Store
from .turn import AgentTurn, Message
from .world import World


@dataclass
class TickReport:
    tick: int
    day: int
    phase: str
    turns: dict[str, AgentTurn | None]
    events: list[Event]
    messages: list[dict]          # delivered chat: {tick, sender, channel, text}
    thoughts: dict[str, str]
    reflections: dict[str, Reflection]
    failures: dict[str, str]


@dataclass
class Stats:
    calls: int = 0
    first_tries: int = 0
    first_try_invalid: int = 0
    failed: int = 0
    cache_hits: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    leaks: int = 0                # private thoughts mentioning stray environment text (see CLI_NOTES)

    @property
    def invalid_rate(self) -> float:
        return (self.first_try_invalid / self.first_tries) if self.first_tries else 0.0


LEAK_WORDS = ("environment", "powershell", "scratchpad", "working directory", "system-reminder",
              "email", "platform", "bash", "claude", "haiku", "token")


class Engine:
    def __init__(self, world: World, agents: dict[str, Agent], provider: Provider,
                 store: Store, run_id: int):
        self.world, self.agents, self.provider = world, agents, provider
        self.store, self.run_id = store, run_id
        self.stats = Stats()

    # ---- construction ----------------------------------------------------------------------
    @classmethod
    def start(cls, world: World, personas: list[Persona], provider: Provider, store: Store,
              label: str = "") -> "Engine":
        roster = {p.name: p.pronouns for p in personas}
        agents = {p.name: Agent(p, roster) for p in personas}
        run_id = store.create_run(world, label=label)
        return cls(world, agents, provider, store, run_id)

    @classmethod
    def resume(cls, run_id: int, personas: list[Persona], provider: Provider, store: Store) -> "Engine":
        world = store.load_world(run_id)
        roster = {p.name: p.pronouns for p in personas}
        agents = {p.name: Agent(p, roster) for p in personas}
        for name, data in store.load_extra(run_id).get("agents", {}).items():
            agents[name].load(data)
        store.set_status(run_id, "running")
        return cls(world, agents, provider, store, run_id)

    # ---- one tick --------------------------------------------------------------------------
    def _logger(self, agent: str, purpose: str):
        def log(resp: LLMResponse | None, ok: bool, error: str | None, attempt: int):
            s = self.stats
            s.calls += 1
            if attempt == 0:
                s.first_tries += 1
                s.first_try_invalid += 0 if ok else 1
            if resp:
                s.cache_hits += int(resp.cache_hit)
                s.input_tokens += resp.input_tokens or 0
                s.output_tokens += resp.output_tokens or 0
            self.store.log_llm_call(
                self.run_id, self.world.tick, agent, purpose, cache_hit=bool(resp and resp.cache_hit),
                latency_ms=resp.latency_ms if resp else None, input_tokens=resp.input_tokens if resp else None,
                output_tokens=resp.output_tokens if resp else None, ok=ok, error=error)
        return log

    async def tick(self) -> TickReport:
        """Run one tick. If a usage limit interrupts the model calls, QuotaExhausted propagates and
        nothing has been mutated or saved, so the tick can simply be run again later."""
        w = self.world
        night = w.phase == "night"
        end_of_day = night
        decide_tasks = {n: a.decide(w, self.provider, self._logger(n, "decide")) for n, a in self.agents.items()}
        reflect_tasks = ({n: a.reflect(w, self.provider, self._logger(n, "reflect")) for n, a in self.agents.items()}
                         if end_of_day else {})
        try:
            results = await asyncio.gather(*decide_tasks.values(), *reflect_tasks.values())
        except QuotaExhausted:
            self.store.set_status(self.run_id, "paused")
            raise
        decided: dict[str, JsonResult[AgentTurn]] = dict(zip(decide_tasks, results[:len(decide_tasks)]))
        reflected: dict[str, JsonResult[Reflection]] = dict(zip(reflect_tasks, results[len(decide_tasks):]))

        # ---- from here on nothing can be interrupted --------------------------------------
        turns: dict[str, AgentTurn | None] = {}
        failures, thoughts = {}, {}
        for n, r in decided.items():
            if r.ok:
                turns[n] = r.value
                thoughts[n] = r.value.thought
                if any(k in r.value.thought.lower() for k in LEAK_WORDS):
                    self.stats.leaks += 1
            else:
                turns[n] = None
                failures[n] = r.error or "invalid output"
                self.stats.failed += 1

        tick_no = w.tick
        phase, day = w.phase, w.day
        intents = {n: t.action for n, t in turns.items() if t and not night}
        events = w.step(intents)
        w_after_tick = w.tick

        delivered, sent_by = self._deliver_messages(tick_no, turns)
        seen = observe(events, list(self.agents))
        for n, agent in self.agents.items():
            agent.commit_turn(tick_no, sent_by.get(n, []))
            agent.pending_obs.extend(seen[n])
        reflections = {}
        for n, r in reflected.items():
            if r.ok:
                reflections[n] = r.value
                self.agents[n].commit_reflection(tick_no, day, r.value)
                self.store.save_beliefs(self.run_id, day, n, self.agents[n].beliefs)
            else:
                failures[f"{n}:reflect"] = r.error or "invalid output"
                self.stats.failed += 1

        extra_events = [("message", m["sender"], m) for m in delivered]
        extra_events += [("system", n, {"type": "decision_failed", "error": e}) for n, e in failures.items()]
        thought_rows = list(thoughts.items()) + [(n, f"[reflection] {r.reflection}") for n, r in reflections.items()]
        self.store.save_tick(self.run_id, w, events, thoughts=thought_rows,
                             extra={"agents": {n: a.dump() for n, a in self.agents.items()}},
                             extra_events=extra_events)
        assert w.tick == w_after_tick
        return TickReport(tick_no, day, phase, turns, events, delivered, thoughts, reflections, failures)

    def _deliver_messages(self, tick: int, turns: dict[str, AgentTurn | None]):
        """Validate channels, queue messages into recipients' inboxes. Delivery is next-tick (simultaneous talk)."""
        delivered, sent_by = [], {}
        names = set(self.agents)
        for sender, turn in turns.items():
            for m in (turn.messages if turn else []):
                if m.channel == "group":
                    recipients = [n for n in names if n != sender]
                elif m.channel.startswith("dm:") and m.channel[3:] in names and m.channel[3:] != sender:
                    recipients = [m.channel[3:]]
                else:
                    continue  # unknown channel or recipient: the message goes nowhere
                rec = {"tick": tick, "sender": sender, "channel": m.channel, "text": m.text}
                delivered.append(rec)
                sent_by.setdefault(sender, []).append(m)
                tag = "[group]" if m.channel == "group" else f"[private message from {sender}]"
                for r in recipients:
                    line = f"{tag} {sender}: {m.text}" if m.channel == "group" else f'{tag}: {m.text}'
                    self.agents[r].inbox.append((tick, m.channel, line))
        return delivered, sent_by

    async def run(self, until_tick: int | None = None, on_tick=None):
        """Run ticks until the game ends or world.tick reaches until_tick."""
        end = self.world.scenario.total_ticks if until_tick is None else min(until_tick, self.world.scenario.total_ticks)
        while self.world.tick < end:
            report = await self.tick()
            if on_tick:
                on_tick(report)
        return self.world
