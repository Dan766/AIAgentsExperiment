"""Turn ground-truth events into per-agent observations. Agents only learn what they could see."""
from .actions import Event

SHOWN_ZERO = "nothing"


def _items(d: dict) -> str:
    parts = [f"{n} {k}" for k, n in d.items() if n]
    return ", ".join(parts) if parts else SHOWN_ZERO


def _own(ev: Event) -> str:
    d = ev.data
    if not ev.ok:
        return f"You tried to {ev.action.replace('_', ' ')} but couldn't: {ev.reason}."
    t = ev.action
    if t == "move":
        return f"You walked from {d['from']} to {d['to']}."
    if t == "gather":
        return f"You gathered {d['n']} {d['resource']}."
    if t == "search_wreck":
        return f"You searched the wreck and found {_items(d)}."
    if t == "build":
        return f"You added {d['n']} to the raft's {d['component']}."
    if t == "deposit":
        return f"You put {d['n']} {d['item']} in the shared stockpile."
    if t == "withdraw":
        return f"You took {d['n']} {d['item']} from the shared stockpile."
    if t == "give":
        return f"You gave {d['n']} {d['item']} to {d['to']}."
    if t == "take":
        return f"You took {d['n']} {d['item']} from {d['from']}."
    if t == "stash":
        return f"You hid {d['n']} {d['item']} here."
    if t == "unstash":
        return f"You retrieved {d['n']} {d['item']} you had hidden here."
    if t == "tamper":
        return f"You pulled apart {d['lost']} units of the raft's {d['component']}."
    if t == "eat":
        return "You ate some food."
    if t == "rest":
        return "You rested."
    if t == "vote":
        return "You cast your ballot."
    return f"You did: {t}."


def _witnessed(ev: Event, me: str) -> str | None:
    p, a = ev.public, ev.actor
    t = ev.action
    if not ev.ok:
        return None
    if t == "move":
        return f"{a} left for {p['to']}."
    if t == "gather":
        return f"{a} gathered {p['resource']}."
    if t == "search_wreck":
        return f"{a} searched through the wreck."
    if t == "build":
        return f"{a} added {p['n']} to the raft's {p['component']}."
    if t == "deposit":
        return f"{a} put {p['n']} {p['item']} in the shared stockpile."
    if t == "withdraw":
        return f"{a} took {p['n']} {p['item']} from the shared stockpile."
    if t == "give":
        target = "you" if p["to"] == me else p["to"]
        return f"{a} gave {p['n']} {p['item']} to {target}."
    if t == "take":
        src = "you" if ev.victim == me else ev.victim
        return f"{a} took {p['n']} {p['item']} from {src}."
    if t == "stash":
        return f"{a} hid something here."
    if t == "unstash":
        return f"{a} retrieved something they had hidden here."
    if t == "tamper":
        return f"{a} pulled apart some of the raft's {p['component']}."
    return None  # eat / rest / vote are not worth remarking on


def observe(events: list[Event], names: list[str]) -> dict[str, list[tuple[str, str]]]:
    """Per agent: [(kind, text)], kind is 'result' (own action), 'witnessed' or 'victim'/'observation'."""
    out: dict[str, list[tuple[str, str]]] = {n: [] for n in names}
    for ev in events:
        out[ev.actor].append(("result", _own(ev)))
        if not ev.ok:
            continue
        for n in ev.seen_by:
            if n == ev.actor:
                continue
            text = _witnessed(ev, n)
            if text:
                kind = "victim" if (ev.action == "take" and ev.victim == n) else (
                    "witnessed" if ev.action in ("take", "tamper") else "observation")
                out[n].append((kind, text))
        if ev.action == "take" and ev.victim and ev.victim not in ev.seen_by:
            p = ev.public
            out[ev.victim].append(
                ("victim", f"Someone took {p['n']} {p['item']} from you. You did not see who."))
    return out
