import asyncio
import json
from typing import Callable

from .base import LLMResponse

REST = json.dumps({"thought": "mock agent idles", "action": {"type": "rest"}, "messages": []})


class MockProvider:
    """Free stand-in for development and tests.

    `script` is either a callable (system, prompt) -> str, or a list of replies consumed in order
    (the last one repeats). Every call is recorded in `calls`. Reply items that are exceptions are raised.
    """

    model = "mock"

    def __init__(self, script: Callable[[str, str], str] | list | None = None, delay: float = 0.0):
        self.script = script if script is not None else [REST]
        self.delay = delay
        self.calls: list[tuple[str, str]] = []
        self.in_flight = 0
        self.max_in_flight = 0

    async def complete(self, system: str, prompt: str) -> LLMResponse:
        self.calls.append((system, prompt))
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
            if callable(self.script):
                reply = self.script(system, prompt)
            else:
                reply = self.script[min(len(self.calls) - 1, len(self.script) - 1)]
            if isinstance(reply, Exception):
                raise reply
            return LLMResponse(text=reply, input_tokens=len(system + prompt) // 4,
                               output_tokens=len(reply) // 4)
        finally:
            self.in_flight -= 1
