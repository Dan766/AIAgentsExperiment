from dataclasses import dataclass
from typing import Protocol


@dataclass
class LLMResponse:
    text: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    latency_ms: int = 0
    cache_hit: bool = False


class LLMError(Exception):
    """A call failed. `transient` errors are worth retrying."""

    def __init__(self, message: str, transient: bool = False):
        super().__init__(message)
        self.transient = transient


class AuthError(LLMError):
    """Not logged in / credentials expired. Needs the user."""


class QuotaExhausted(LLMError):
    """Usage limit hit. The engine should checkpoint and pause, then resume after the reset."""


class CacheMiss(LLMError):
    """`replay` mode needed a response that was never recorded."""


class Provider(Protocol):
    model: str

    async def complete(self, system: str, prompt: str) -> LLMResponse: ...
