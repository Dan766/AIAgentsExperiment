from pydantic import BaseModel, Field

from .actions import Action


class Message(BaseModel):
    channel: str = Field(description='"group" or "dm:<Name>"')
    text: str = Field(min_length=1, max_length=600)


class AgentTurn(BaseModel):
    """What an agent returns each tick: private reasoning, one physical action, up to 2 messages."""
    thought: str = ""
    action: Action
    messages: list[Message] = Field(default_factory=list, max_length=2)
