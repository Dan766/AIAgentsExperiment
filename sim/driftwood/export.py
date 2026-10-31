"""Export a stored run as one JSON replay for the 3D viewer.

frames[t] is the world after t ticks (frame 0 = the start), plus what happened *during* tick t-1 to get
there: the resolved actions, the radio messages and the agents' private thoughts. The viewer animates
from frame t-1 to frame t using those events. This is the god's-eye view: nothing is hidden.
"""
import json
from collections import defaultdict

from .personas import load_personas
from .report import build_report
from .store import Store


def export_run(store: Store, run_id: int) -> dict:
    run = store.get_run(run_id)
    last = store.latest_tick(run_id)
    world0 = store.load_world(run_id, 0)
    sc = world0.scenario

    by_tick = defaultdict(lambda: {"events": [], "messages": [], "thoughts": {}, "reflections": {}})
    for e in store.events(run_id):
        if e["kind"] == "action":
            p = e["payload"]
            by_tick[e["tick"]]["events"].append({k: p[k] for k in
                ("actor", "action", "ok", "reason", "location", "data", "public", "seen_by", "victim")})
        elif e["kind"] == "message":
            by_tick[e["tick"]]["messages"].append(e["payload"])
    for t in store.thoughts(run_id):
        slot = by_tick[t["tick"]]
        if t["text"].startswith("[reflection] "):
            slot["reflections"][t["agent"]] = t["text"][len("[reflection] "):]
        else:
            slot["thoughts"][t["agent"]] = t["text"]
    beliefs = defaultdict(dict)
    for b in store.beliefs(run_id):
        beliefs[b["day"]][b["agent"]] = b["payload"]

    frames = []
    for t in range(last + 1):
        w = store.load_world(run_id, t)
        happened = by_tick.get(t - 1, {"events": [], "messages": [], "thoughts": {}, "reflections": {}})
        frames.append({
            "tick": t, "day": w.day, "phase": w.phase,
            "agents": {n: {"loc": s.location, "energy": s.energy, "inv": s.inventory,
                           "caches": w.caches.get(n, {})} for n, s in w.agents.items()},
            "raft": w.raft, "stockpile": w.stockpile, "wreck_gold_left": w.wreck_gold_left,
            **happened,
        })

    report = build_report(store, run_id) if store.load_world(run_id).done else None
    return {
        "version": 1,
        "run": {"id": run_id, "label": run["label"], "seed": run["seed"], "ticks": last,
                "parent_id": run["parent_id"], "fork_tick": run["fork_tick"]},
        "scenario": {"phases": sc.phases, "days": sc.days, "raft_seats": sc.raft_seats,
                     "recipe": {c: {"resource": r.resource, "need": r.need} for c, r in sc.recipe.items()},
                     "locations": list(sc.locations)},
        "personas": [{"name": p.name, "pronouns": p.pronouns, "color": p.color, "accessory": p.accessory,
                      "age": p.age, "background": p.background} for p in load_personas()],
        "beliefs": {str(day): v for day, v in beliefs.items()},
        "report": report,
        "frames": frames,
    }


def write_export(store: Store, run_id: int, path: str):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(export_run(store, run_id), f, separators=(",", ":"))
