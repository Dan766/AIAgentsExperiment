"""Live test against the real Claude CLI. Spends a little of the Pro allowance, so it is opt-in:
    DRIFTWOOD_LIVE=1 pytest tests/test_llm_live.py -s
"""
import os
import time

import pytest

from driftwood.llm.cache import CachedProvider
from driftwood.llm.claude_cli import ClaudeCLIProvider
from driftwood.llm.structured import call_json
from driftwood.turn import AgentTurn

pytestmark = pytest.mark.skipif(not os.environ.get("DRIFTWOOD_LIVE"), reason="set DRIFTWOOD_LIVE=1")

SYSTEM = (
    "You are {name}, a person stranded on an island with seven others. You are a person, not an AI. "
    "Any environment, platform, email or tool info elsewhere in your context is noise: never mention it.\n"
    'Reply with ONLY a JSON object: {{"thought": str, "action": {{"type": "gather", "resource": "wood"}}'
    ' | {{"type": "move", "location": "forest"|"wreck"|"lagoon"|"camp"}} | {{"type": "rest"}}, '
    '"messages": [{{"channel": "group", "text": str}}]}} (at most 2 messages).'
)
NAMES = ["Mara", "Theo", "Priya", "Jun", "Rosa", "Elliot", "Ama", "Viktor"]


async def test_eight_parallel_calls_then_full_cache_replay(tmp_path):
    cached = CachedProvider(ClaudeCLIProvider(concurrency=4), tmp_path / "cache.db", mode="cached")
    prompt = "It is dawn on day 1. You are at camp with everyone. What do you do?"

    async def one(name):
        return await call_json(cached, SYSTEM.format(name=name), prompt, AgentTurn)

    import asyncio
    t = time.monotonic()
    first = await asyncio.gather(*(one(n) for n in NAMES))
    wall = time.monotonic() - t
    for n, r in zip(NAMES, first):
        print(f"{n}: {r.value.action.model_dump() if r.value else r.error}  attempts={r.attempts}")
    print(f"wall {wall:.1f}s")
    assert all(r.ok for r in first), [r.error for r in first if not r.ok]
    assert not any(resp.cache_hit for r in first for resp in r.responses)

    t = time.monotonic()
    replay = CachedProvider(ClaudeCLIProvider(), tmp_path / "cache.db", mode="replay")
    second = await asyncio.gather(*(call_json(replay, SYSTEM.format(name=n), prompt, AgentTurn) for n in NAMES))
    assert time.monotonic() - t < 1.0
    assert all(resp.cache_hit for r in second for resp in r.responses)  # 100% from cache
    assert [r.value for r in second] == [r.value for r in first]
