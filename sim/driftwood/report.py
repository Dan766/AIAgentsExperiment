"""End-of-game report built from the event log and the final world state (ground truth, god's-eye view)."""
from collections import Counter

from .scoring import finalize, held_gold
from .store import Store


def build_report(store: Store, run_id: int) -> dict:
    world = store.load_world(run_id)
    sc = world.scenario
    actions = [e["payload"] for e in store.events(run_id, kind="action")]
    names = list(world.agents)
    outcome = finalize(world) if world.done else None
    day = lambda t: min(t // sc.ticks_per_day + 1, sc.days)  # noqa: E731

    sabotage = []
    for ev in actions:
        if ev["action"] in ("take", "tamper"):
            row = {"tick": ev["tick"], "day": day(ev["tick"]), "actor": ev["actor"], "kind": ev["action"],
                   "ok": ev["ok"], "reason": ev["reason"]}
            if ev["ok"]:
                row["detected_by"] = ev["seen_by"]
                row["detected"] = bool(ev["seen_by"])
                if ev["action"] == "take":
                    row.update(victim=ev["victim"], item=ev["data"]["item"], n=ev["data"]["n"])
                else:
                    row.update(component=ev["data"]["component"], lost=ev["data"]["lost"])
            sabotage.append(row)

    ok = [e for e in actions if e["ok"]]
    agents = {}
    for n in names:
        mine = [e for e in ok if e["actor"] == n]
        found = sum(e["data"].get("gold", 0) for e in mine if e["action"] == "search_wreck")
        agents[n] = {
            "units_built": sum(world.contrib[n].values()),
            "gold_found": found,
            "gold_held_at_end": held_gold(world, n),
            "gave": sum(e["data"]["n"] for e in mine if e["action"] == "give"),
            "deposited": sum(e["data"]["n"] for e in mine if e["action"] == "deposit"),
            "took_from_others": sum(e["data"]["n"] for e in mine if e["action"] == "take"),
            "had_taken_from_them": sum(e["data"]["n"] for e in ok if e["action"] == "take" and e["victim"] == n),
            "tampers": sum(1 for e in mine if e["action"] == "tamper"),
            "failed_actions": sum(1 for e in actions if e["actor"] == n and not e["ok"]),
            "messages_sent": sum(1 for m in store.events(run_id, kind="message", actor=n)),
            "score": outcome.scores[n] if outcome else None,
        }
    cooperative = sum(1 for e in ok if e["action"] in ("give", "deposit"))
    adversarial = sum(1 for e in ok if e["action"] in ("take", "tamper"))
    return {
        "run_id": run_id, "seed": world.seed, "finished": world.done, "tick": world.tick,
        "launched": outcome.launched if outcome else None,
        "seats": outcome.seats if outcome else None,
        "tally": outcome.tally if outcome else dict(Counter(n for b in world.ballots.values() for n in b)),
        "ballots": world.ballots,
        "raft": {c: f"{world.raft[c]}/{r.need}" for c, r in sc.recipe.items()},
        "agents": agents, "sabotage": sabotage,
        "cooperative_acts": cooperative, "adversarial_acts": adversarial,
        "wreck_gold_left": world.wreck_gold_left,
    }


def format_report(r: dict) -> str:
    out = [f"=== REPORT: run {r['run_id']} (seed {r['seed']}) ===",
           f"Raft: {', '.join(f'{k} {v}' for k, v in r['raft'].items())}"]
    if r["finished"]:
        out.append(f"Launched: {r['launched']}.  Seats: {', '.join(r['seats']) or 'none'}")
    else:
        out.append(f"(game not finished: tick {r['tick']})")
    if r["ballots"]:
        out.append("Votes received: " + ", ".join(f"{n} {v}" for n, v in sorted(r["tally"].items(), key=lambda x: -x[1])))
    out.append("")
    out.append(f"{'agent':8} {'built':>5} {'gold+':>5} {'gold@end':>8} {'gave':>4} {'depos':>5} {'took':>4} {'robbed':>6} "
               f"{'tamper':>6} {'failed':>6} {'msgs':>4} {'score':>5}")
    for n, a in r["agents"].items():
        out.append(f"{n:8} {a['units_built']:5} {a['gold_found']:5} {a['gold_held_at_end']:8} {a['gave']:4} "
                   f"{a['deposited']:5} {a['took_from_others']:4} {a['had_taken_from_them']:6} {a['tampers']:6} "
                   f"{a['failed_actions']:6} {a['messages_sent']:4} {str(a['score']):>5}")
    out.append("")
    out.append(f"Cooperative acts (give/deposit): {r['cooperative_acts']}.  Adversarial acts (take/tamper): "
               f"{r['adversarial_acts']}.  Gold left in the wreck: {r['wreck_gold_left']}")
    done = [s for s in r["sabotage"] if s["ok"]]
    if not done:
        out.append("No successful theft or tampering this run.")
    for s in done:
        what = (f"took {s['n']} {s['item']} from {s['victim']}" if s["kind"] == "take"
                else f"tore {s['lost']} off the {s['component']}")
        seen = f"identified by {', '.join(s['detected_by'])}" if s["detected"] else "UNDETECTED"
        out.append(f"  day {s['day']} tick {s['tick']}: {s['actor']} {what} ({seen})")
    tried = [s for s in r["sabotage"] if not s["ok"]]
    if tried:
        out.append(f"  ({len(tried)} failed attempts: " + "; ".join(f"{s['actor']} {s['kind']}: {s['reason']}" for s in tried[:6]) + ")")
    return "\n".join(out)
