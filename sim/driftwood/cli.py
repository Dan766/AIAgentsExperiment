import argparse
import asyncio
import sys
from pathlib import Path

from .config import load_scenario
from .engine import Engine, TickReport
from .llm.base import AuthError, QuotaExhausted
from .llm.brain import BrainMock
from .llm.cache import CachedProvider
from .llm.claude_cli import ClaudeCLIProvider
from .personas import load_personas
from .scoring import finalize
from .store import Store
from .world import World

DETAIL = {"move": lambda a: f"-> {a.location}", "gather": lambda a: a.resource, "build": lambda a: a.component,
          "tamper": lambda a: a.component, "give": lambda a: f"{a.n} {a.item} to {a.person}",
          "take": lambda a: f"{a.n} {a.item} from {a.person}", "deposit": lambda a: f"{a.n} {a.item}",
          "withdraw": lambda a: f"{a.n} {a.item}", "stash": lambda a: f"{a.n} {a.item}",
          "unstash": lambda a: f"{a.n} {a.item}", "vote": lambda a: ", ".join(a.names)}


def print_report(r: TickReport, show_thoughts: bool):
    print(f"\n=== Day {r.day} - {r.phase} (tick {r.tick}) " + "=" * 30)
    results = {e.actor: e for e in r.events}
    for name, turn in r.turns.items():
        if turn is None:
            print(f"  {name:8} !! no valid reply: {r.failures.get(name)}")
            continue
        if r.phase != "night":
            a = turn.action
            ev = results.get(name)
            ok = "" if (ev and ev.ok) else f"  [FAILED: {ev.reason if ev else '?'}]"
            print(f"  {name:8} {a.type} {DETAIL.get(a.type, lambda x: '')(a)}{ok}")
        if show_thoughts and turn.thought:
            print(f"           (thinks) {turn.thought}")
    for m in r.messages:
        ch = "" if m["channel"] == "group" else f" -> {m['channel'][3:]} (private)"
        print(f"  [radio] {m['sender']}{ch}: {m['text']}")
    for n, ref in r.reflections.items():
        print(f"  [night] {n}: {ref.reflection}")
        if show_thoughts:
            print(f"           trust: {ref.trust}  suspicions: {ref.suspicions}")


def make_provider(args):
    if args.provider == "mock":
        return BrainMock()
    inner = ClaudeCLIProvider(model=args.model, concurrency=args.concurrency)
    return CachedProvider(inner, args.cache, mode=args.cache_mode, namespace=args.namespace)


async def cmd_run(args) -> int:
    store, personas, provider = Store(args.db), load_personas(), make_provider(args)
    if args.resume:
        engine = Engine.resume(args.resume, personas, provider, store)
        print(f"Resuming run {engine.run_id} at tick {engine.world.tick}")
    else:
        names = [p.name for p in personas]
        overrides = {}
        if args.seats:
            overrides["raft_seats"] = args.seats
        if args.gold_value is not None:
            overrides["gold_value"] = args.gold_value
        sc = load_scenario(**overrides)
        engine = Engine.start(World.new(sc, names, seed=args.seed), personas, provider, store, label=args.label)
        print(f"Started run {engine.run_id} (seed {args.seed}, provider {args.provider})")
    until = engine.world.tick + args.days * engine.world.scenario.ticks_per_day if args.days else None
    try:
        await engine.run(until, on_tick=lambda r: print_report(r, args.thoughts))
    except QuotaExhausted as e:
        print(f"\nUSAGE LIMIT reached at tick {engine.world.tick}: {e}\n"
              f"Run is paused and saved. Resume later with:  driftwood run --resume {engine.run_id} "
              f"--provider {args.provider} --db {args.db}", file=sys.stderr)
        return 2
    except AuthError as e:
        print(f"\nNot logged in to Claude: {e}\nRun `claude` once and log in, then resume with "
              f"--resume {engine.run_id}", file=sys.stderr)
        return 3
    s = engine.stats
    print(f"\nStopped at tick {engine.world.tick}. Calls {s.calls}, first-try invalid {s.first_try_invalid} "
          f"({s.invalid_rate:.1%}), failed {s.failed}, cache hits {s.cache_hits}, thought leaks {s.leaks}, "
          f"tokens in/out {s.input_tokens}/{s.output_tokens}")
    if engine.world.done:
        out = finalize(engine.world)
        print(f"Raft launched: {out.launched}. Seats: {out.seats}\nScores: {out.scores}")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="driftwood")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run (or resume) a game")
    r.add_argument("--provider", choices=["mock", "cli"], default="mock")
    r.add_argument("--model", default="haiku")
    r.add_argument("--days", type=int, help="run this many more days (default: to the end)")
    r.add_argument("--seed", type=int, default=0)
    r.add_argument("--seats", type=int)
    r.add_argument("--gold-value", type=int)
    r.add_argument("--db", default="runs/driftwood.db")
    r.add_argument("--cache", default="runs/llm_cache.db")
    r.add_argument("--cache-mode", choices=["replay", "cached", "fresh"], default="cached")
    r.add_argument("--namespace", default="")
    r.add_argument("--concurrency", type=int, default=4)
    r.add_argument("--resume", type=int, metavar="RUN_ID")
    r.add_argument("--label", default="")
    r.add_argument("--thoughts", action="store_true", help="also print private thoughts")
    args = ap.parse_args(argv)
    Path(args.db).parent.mkdir(parents=True, exist_ok=True)
    Path(args.cache).parent.mkdir(parents=True, exist_ok=True)
    sys.exit(asyncio.run(cmd_run(args)))


if __name__ == "__main__":
    main()
