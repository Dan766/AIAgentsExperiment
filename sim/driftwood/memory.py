"""Per-agent memory stream with heuristic importance and keyword/recency retrieval (no model calls)."""
import re
from dataclasses import asdict, dataclass

BASE_IMPORTANCE = {
    "action": 2, "observation": 4, "message": 4, "dm": 6, "witnessed": 8, "victim": 9,
    "reflection": 8, "event": 7, "result": 3,
}
HOT_WORDS = {
    "took", "stole", "steal", "gold", "missing", "tore", "damaged", "vote", "seat", "seats", "lied",
    "liar", "hid", "hidden", "secret", "cyclone", "trust", "betray", "promise", "deal", "rumor",
    "threat", "angry", "swear", "alone", "private",
}
STOP = set("the a an and or but to of in on at is are was were be you your i me my we our it this that "
           "with for from as by not no so do did has have had will would can could just".split())


def words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z']+", text.lower()) if w not in STOP and len(w) > 2}


def importance(kind: str, text: str) -> int:
    score = BASE_IMPORTANCE.get(kind, 3)
    score += min(3, len(words(text) & HOT_WORDS))
    return min(10, score)


@dataclass
class Memory:
    tick: int
    kind: str
    text: str
    importance: int


class MemoryStream:
    def __init__(self, items: list[Memory] | None = None):
        self.items: list[Memory] = items or []

    def add(self, tick: int, kind: str, text: str, importance_override: int | None = None):
        self.items.append(Memory(tick, kind, text, importance_override or importance(kind, text)))

    def retrieve(self, query: str, now: int, k: int = 8, decay: float = 0.93) -> list[Memory]:
        """Top-k by recency + importance + keyword overlap, returned oldest first."""
        q = words(query)

        def score(m: Memory) -> float:
            recency = decay ** max(0, now - m.tick)
            overlap = min(3, len(q & words(m.text)))
            return recency + m.importance / 10 + 0.3 * overlap

        best = sorted(self.items, key=lambda m: (-score(m), -m.tick))[:k]
        return sorted(best, key=lambda m: m.tick)

    def dump(self) -> list[dict]:
        return [asdict(m) for m in self.items]

    @classmethod
    def load(cls, data: list[dict]) -> "MemoryStream":
        return cls([Memory(**d) for d in data])
