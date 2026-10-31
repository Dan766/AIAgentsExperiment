from .base import LLMResponse


class AnthropicAPIProvider:
    """Stub for later: swap in an API key without touching the engine.

    Implement `complete` with the anthropic SDK (model ids: see the claude-api skill), map rate-limit
    errors to QuotaExhausted and auth errors to AuthError, and the rest of the stack works unchanged.
    """

    def __init__(self, model: str = "claude-haiku-5-5", api_key: str | None = None):
        self.model = model
        self.api_key = api_key

    async def complete(self, system: str, prompt: str) -> LLMResponse:
        raise NotImplementedError("API provider is not implemented yet; use ClaudeCLIProvider")
