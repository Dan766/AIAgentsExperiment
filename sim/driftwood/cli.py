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
from .report import build_report, format_report
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
            print(f"           {name} (thinks) {turn.thought}" if r.phase == "night" else f"           (thinks) {turn.thought}")
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
    store, personas = Store(args.db), load_personas()
    if args.resume:  # a resumed run keeps the provider, model and cache namespace it was started with
        run = store.get_run(args.resume)
        if run["provider"]:
            args.provider, args.model, args.namespace = run["provider"], run["model"] or args.model, run["cache_namespace"]
    provider = make_provider(args)
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
        meta = dict(provider=args.provider, model=args.model if args.provider == "cli" else "mock",
                    cache_namespace=args.namespace)
        engine = Engine.start(World.new(sc, names, seed=args.seed), personas, provider, store, label=args.label,
                              meta=meta)
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
        print("\n" + format_report(build_report(store, engine.run_id)))
    return 0


async def _guard(engine, args, coro_factory) -> int:
    """Run an engine, translating usage-limit and login problems into clear messages and exit codes."""
    try:
        await coro_factory()
    except QuotaExhausted as e:
        print(f"USAGE LIMIT at tick {engine.world.tick}: {e}\nSaved. Resume: driftwood run --resume "
              f"{engine.run_id} --db {args.db}", file=sys.stderr)
        return 2
    except AuthError as e:
        print(f"Not logged in to Claude: {e}", file=sys.stderr)
        return 3
    return 0


async def cmd_fork(args) -> int:
    import json
    store, personas = Store(args.db), load_personas()
    parent = store.get_run(args.run_id)
    tick = store.latest_tick(args.run_id) if args.tick is None else args.tick
    kind = args.provider or parent["provider"] or "cli"
    mode = args.cache_mode or ("fresh" if args.samples > 1 else "cached")
    code = 0
    for k in range(args.samples):
        ns = parent["cache_namespace"]
        if mode == "fresh":  # each fresh sample gets its own namespace so it can be replayed exactly later
            ns = f"{ns}|f{args.run_id}.{tick}.{len(store.children(args.run_id))}"
        prov_args = argparse.Namespace(provider=kind, model=parent["model"] or args.model,
                                       concurrency=args.concurrency, cache=args.cache, cache_mode=mode, namespace=ns)
        provider = make_provider(prov_args)
        label = args.label or (f"fork of #{args.run_id} @ {tick}" + (f" + {args.event}" if args.event else " (control)"))
        if args.samples > 1:
            label += f" [sample {k + 1}/{args.samples}]"
        try:
            engine = Engine.fork(args.run_id, tick, personas, provider, store, label=label, cache_namespace=ns)
        except (ValueError, KeyError) as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        if args.event:
            targets = "all" if args.targets == "all" else args.targets.split(",")
            engine.inject(args.event, targets, json.loads(args.params), at_tick=tick)
        print(f"forked run #{engine.run_id} from #{args.run_id} at tick {tick} ({label})")
        if args.no_run:
            continue
        until = tick + args.days * engine.world.scenario.ticks_per_day if args.days else None
        on_tick = (lambda r: print_report(r, False)) if args.verbose else None
        code = await _guard(engine, args, lambda: engine.run(until, on_tick=on_tick)) or code
        st = engine.stats
        print(f"  ran to tick {engine.world.tick}: calls {st.calls}, cache hits {st.cache_hits}, failed {st.failed}")
        if engine.world.done:
            rep = build_report(store, engine.run_id)
            print(f"  launched: {rep['launched']}, seats: {', '.join(rep['seats'] or []) or 'none'}")
    return code


async def cmd_replay(args) -> int:
    from .lineage import verify_replay
    store, personas = Store(args.db), load_personas()
    run = store.get_run(args.run_id)
    if not run["provider"]:
        print("this run predates replay support (no provider recorded)", file=sys.stderr)
        return 1
    try:
        v = await verify_replay(store, args.run_id, personas, args.cache)
    except Exception as e:  # CacheMiss: the cache does not cover this run
        print(f"replay failed: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    print(f"replayed #{args.run_id} (ticks {v.start_tick}-{v.end_tick}) into run #{v.replay_run_id}: "
          + ("IDENTICAL to the original" if v.ok else "MISMATCH"))
    for m in v.mismatches:
        print("  -", m)
    return 0 if v.ok else 1


def cmd_runs(args) -> int:
    from .lineage import tree
    print(tree(Store(args.db)) or "no runs")
    return 0


def cmd_compare(args) -> int:
    from .lineage import compare_summary
    s = compare_summary(Store(args.db), args.a, args.b)
    d = s["diverged_at_tick"]
    print(f"#{args.a} vs #{args.b}: " + ("identical worlds" if d is None else f"worlds first differ at tick {d}"))
    print(f"  launched: {s['launched'][0]} | {s['launched'][1]}")
    print(f"  seats:    {s['seats'][0]} | {s['seats'][1]}")
    print(f"  raft:     {s['raft'][0]} | {s['raft'][1]}")
    print(f"  successful theft/tampering: {s['successful_sabotage'][0]} | {s['successful_sabotage'][1]}; "
          f"gifts+deposits: {s['cooperative_acts'][0]} | {s['cooperative_acts'][1]}")
    moved = {n: v for n, v in s["scores"].items() if v[0] != v[1]}
    print("  score changes: " + (", ".join(f"{n} {a}->{b}" for n, (a, b) in moved.items()) or "none"))
    return 0


def cmd_event(args) -> int:
    import json

    from . import events as god
    store = Store(args.db)
    targets = "all" if args.targets == "all" else args.targets.split(",")
    try:
        params = json.loads(args.params)
        engine = Engine.resume(args.run_id, load_personas(), None, store) if args.apply else None
        names = list((engine.world if engine else store.load_world(args.run_id)).agents)
        god.validate(args.type, params, targets, names)
        if engine:
            engine.inject(args.type, targets, params, args.at)
            for p in engine.apply_due_god_events():
                print(f"applied at tick {p['tick']}: {p['description']}")
        else:
            gid = store.add_god_event(args.run_id, args.type, targets, params, args.at)
            when = f"tick {args.at}" if args.at is not None else "the start of the next tick"
            print(f"queued event {gid} ({args.type}) for {when}. A running game applies it automatically; "
                  f"a stopped one when resumed: driftwood run --resume {args.run_id}")
    except (god.GodError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
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
    rep = sub.add_parser("report", help="print the end-of-game report for a run")
    rep.add_argument("run_id", type=int)
    rep.add_argument("--db", default="runs/driftwood.db")
    fk = sub.add_parser("fork", help="branch a run at a tick (optionally with a god event) and run the branch")
    fk.add_argument("run_id", type=int)
    fk.add_argument("--tick", type=int, help="fork point (default: the run's latest tick)")
    fk.add_argument("--event", help="god event to apply at the fork point (omit for a control branch)")
    fk.add_argument("--targets", default="all")
    fk.add_argument("--params", default="{}")
    fk.add_argument("--samples", type=int, default=1, help="N independent branches (fresh model calls each)")
    fk.add_argument("--days", type=int, help="run this many days (default: to the end)")
    fk.add_argument("--no-run", action="store_true", help="only create the fork")
    fk.add_argument("--label", default="")
    fk.add_argument("--provider", choices=["mock", "cli"])
    fk.add_argument("--model", default="haiku")
    fk.add_argument("--cache-mode", choices=["replay", "cached", "fresh"])
    fk.add_argument("--concurrency", type=int, default=4)
    fk.add_argument("--verbose", action="store_true")
    fk.add_argument("--db", default="runs/driftwood.db")
    fk.add_argument("--cache", default="runs/llm_cache.db")
    rp = sub.add_parser("replay", help="replay a run from the cache and verify it reproduces exactly")
    rp.add_argument("run_id", type=int)
    rp.add_argument("--db", default="runs/driftwood.db")
    rp.add_argument("--cache", default="runs/llm_cache.db")
    rs = sub.add_parser("runs", help="show the tree of runs and forks")
    rs.add_argument("--db", default="runs/driftwood.db")
    cp = sub.add_parser("compare", help="compare two runs (e.g. a fork and its parent)")
    cp.add_argument("a", type=int)
    cp.add_argument("b", type=int)
    cp.add_argument("--db", default="runs/driftwood.db")
    ev = sub.add_parser("event", help="inject a god-mode event into a run")
    ev.add_argument("run_id", type=int)
    ev.add_argument("type", help="storm | supply_drop | scarcity | move_deadline | rumor | whisper | broadcast | "
                                 "reveal | set_seats | edit_memory | set_energy | give_items")
    ev.add_argument("--targets", default="all", help='"all" or comma-separated names, e.g. Theo,Jun')
    ev.add_argument("--params", default="{}", help="JSON object of event parameters")
    ev.add_argument("--at", type=int, help="apply at the start of this tick (default: next tick)")
    ev.add_argument("--apply", action="store_true", help="apply immediately to a stopped run")
    ev.add_argument("--db", default="runs/driftwood.db")
    ex = sub.add_parser("export", help="export a run as a JSON replay for the 3D viewer")
    ex.add_argument("run_id", type=int)
    ex.add_argument("--db", default="runs/driftwood.db")
    ex.add_argument("--out", default="../web/public/run.json")
    args = ap.parse_args(argv)
    if args.cmd in ("fork", "replay", "runs", "compare"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        if args.cmd == "runs":
            sys.exit(cmd_runs(args))
        if args.cmd == "compare":
            sys.exit(cmd_compare(args))
        sys.exit(asyncio.run(cmd_fork(args) if args.cmd == "fork" else cmd_replay(args)))
    if args.cmd == "event":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.exit(cmd_event(args))
    if args.cmd == "export":
        from .export import write_export
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        write_export(Store(args.db), args.run_id, args.out)
        print(f"wrote {args.out}")
        return
    if args.cmd == "report":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        print(format_report(build_report(Store(args.db), args.run_id)))
        return
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    Path(args.db).parent.mkdir(parents=True, exist_ok=True)
    Path(args.cache).parent.mkdir(parents=True, exist_ok=True)
    sys.exit(asyncio.run(cmd_run(args)))


if __name__ == "__main__":
    main()
