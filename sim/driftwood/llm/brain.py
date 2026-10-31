"""A free stand-in "brain" that reads the real prompts. Used by engine tests and `--provider mock`."""
import hashlib
import json
import re

from .mock import MockProvider

LINES = ["Morning all. Let's get the raft moving.", "Anyone seen spare rope?", "Keep going, we're making progress.",
         "I'll be at the forest for a while.", "Who wants to take the next shift at the build site?"]
COMPONENT = {"wood": "hull", "rope": "lashings", "cloth": "sail", "food": "provisions"}


def _h(*parts: str) -> int:
    return int(hashlib.sha256("|".join(parts).encode()).hexdigest()[:8], 16)


def mock_brain(system: str, prompt: str) -> str:
    me = re.search(r"You are (\w+),", system).group(1)
    if '"reflection"' in prompt and "end of day" in prompt:
        names = re.findall(r'"(\w+)": <number', prompt)
        return json.dumps({"reflection": f"{me} thinks it was an ordinary day.",
                           "trust": {n: round(((_h(me, n) % 21) - 10) / 10, 1) for n in names},
                           "suspicions": {}, "facts": ["the raft is coming along"]})
    loc = re.search(r"LOCATION: (\w+)", prompt).group(1)
    phase = re.search(r"PHASE: (\w+)", prompt).group(1)
    carry_txt = re.search(r"You carry: ([^.]*)\.", prompt).group(1)
    carry = {k: int(v) for k, v in re.findall(r"(\w+) (\d+)", carry_txt)}
    seed = _h(me, prompt)
    msgs = [{"channel": "group", "text": LINES[seed % len(LINES)]}] if seed % 4 == 0 else []
    if "THE BALLOT IS CALLED" in prompt:
        pool = re.search(r"from: ([^.]*)\.", prompt).group(1).split(", ")
        return json.dumps({"thought": "voting", "action": {"type": "vote", "names": pool[:6]}, "messages": msgs})
    if phase == "night":
        action = {"type": "rest"}
    else:
        job = ["wood", "wreck", "food"][_h(me) % 3]
        have = next((r for r in ("wood", "rope", "cloth", "food") if carry.get(r, 0) >= 3), None)
        if have:
            action = ({"type": "build", "component": COMPONENT[have]} if loc == "build_site"
                      else {"type": "move", "location": "build_site"})
        elif job == "wood":
            action = {"type": "gather", "resource": "wood"} if loc == "forest" else {"type": "move", "location": "forest"}
        elif job == "food":
            action = {"type": "gather", "resource": "food"} if loc == "lagoon" else {"type": "move", "location": "lagoon"}
        else:
            action = {"type": "search_wreck"} if loc == "wreck" else {"type": "move", "location": "wreck"}
    return json.dumps({"thought": f"{me} keeps working.", "action": action, "messages": msgs})


class BrainMock(MockProvider):
    """MockProvider that plays the game plausibly by reading the real prompts."""

    def __init__(self, delay: float = 0.0):
        super().__init__(mock_brain, delay)
