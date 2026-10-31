from pydantic import BaseModel, Field, field_validator
from pydantic_core import PydanticCustomError

from .actions import Action

# Output rules that change what a model reply is allowed to be. They are recorded on every run (runs.rules) and
# re-applied on resume, fork and replay: changing them later must never alter how an old run replays, because a
# reply that was rejected-then-retried under one limit would be accepted outright under another.
LIMITS = {"message_chars": 900}


class Message(BaseModel):
    channel: str = Field(description='"group" or "dm:<Name>"')
    text: str = Field(min_length=1)

    @field_validator("text")
    @classmethod
    def _short_enough(cls, v: str) -> str:
        limit = LIMITS["message_chars"]
        if len(v) > limit:
            # same wording pydantic's own max_length uses: the text is echoed to the model on retry, so it must match
            raise PydanticCustomError("string_too_long", "String should have at most {max_length} characters",
                                      {"max_length": limit})
        return v


class AgentTurn(BaseModel):
    """What an agent returns each tick: private reasoning, one physical action, up to 2 messages."""
    thought: str = ""
    action: Action
    messages: list[Message] = Field(default_factory=list, max_length=2)
