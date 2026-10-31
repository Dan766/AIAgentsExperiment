"""Ask a provider for JSON, validate it against a pydantic model, retry once with the error."""
import json
from dataclasses import dataclass, field
from typing import Callable, Generic, TypeVar

from pydantic import BaseModel, ValidationError

from .base import LLMResponse, Provider

T = TypeVar("T", bound=BaseModel)


def extract_json(text: str) -> dict:
    """Pull the first top-level JSON object out of a reply (tolerates prose and ``` fences)."""
    start = text.find("{")
    while start != -1:
        depth, in_str, esc = 0, False, False
        for i in range(start, len(text)):
            c = text[i]
            if in_str:
                if esc:
                    esc = False
                elif c == "\\":
                    esc = True
                elif c == '"':
                    in_str = False
                continue
            if c == '"':
                in_str = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    try:
                        obj = json.loads(text[start:i + 1])
                    except json.JSONDecodeError:
                        break
                    if isinstance(obj, dict):
                        return obj
                    break
        start = text.find("{", start + 1)
    raise ValueError("no JSON object found in reply")


@dataclass
class JsonResult(Generic[T]):
    value: T | None
    ok: bool
    attempts: int
    responses: list[LLMResponse] = field(default_factory=list)
    error: str | None = None


# log(response_or_None, ok, error, attempt): called once per attempt so callers can record llm_calls.
LogFn = Callable[[LLMResponse | None, bool, str | None, int], None]


async def call_json(provider: Provider, system: str, prompt: str, schema: type[T],
                    log: LogFn | None = None, retries: int = 1) -> JsonResult[T]:
    """QuotaExhausted, AuthError and CacheMiss propagate; malformed output returns ok=False."""
    responses: list[LLMResponse] = []
    error = None
    current = prompt
    for attempt in range(retries + 1):
        resp = await provider.complete(system, current)
        responses.append(resp)
        try:
            value = schema.model_validate(extract_json(resp.text))
            if log:
                log(resp, True, None, attempt)
            return JsonResult(value, True, attempt + 1, responses)
        except (ValueError, ValidationError) as e:
            error = _short(e)
            if log:
                log(resp, False, error, attempt)
            current = (f"{prompt}\n\nYour previous reply was rejected: {error}\n"
                       f"Reply again with only the JSON object, nothing else.")
    return JsonResult(None, False, retries + 1, responses, error)


def _short(e: Exception) -> str:
    if isinstance(e, ValidationError):
        return "; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors()[:4])
    return str(e)
