import asyncio
import json

import pytest

from driftwood.actions import Gather, Rest
from driftwood.llm.base import AuthError, CacheMiss, LLMError, LLMResponse, QuotaExhausted
from driftwood.llm.cache import CachedProvider, cache_key
from driftwood.llm.claude_cli import ClaudeCLIProvider, interpret
from driftwood.llm.mock import MockProvider
from driftwood.llm.structured import call_json, extract_json
from driftwood.store import Store
from driftwood.turn import AgentTurn

GOOD = json.dumps({"thought": "need wood", "action": {"type": "gather", "resource": "wood"},
                   "messages": [{"channel": "group", "text": "heading to the forest"}]})


# ---- extract_json ------------------------------------------------------------------------
def test_extract_json_variants():
    assert extract_json('{"a": 1}') == {"a": 1}
    assert extract_json('Sure! Here you go:\n```json\n{"a": {"b": [1, 2]}}\n```\nDone.') == {"a": {"b": [1, 2]}}
    assert extract_json('{"t": "braces } in { strings", "n": 2}') == {"t": "braces } in { strings", "n": 2}
    assert extract_json('noise {not json} then {"ok": true}') == {"ok": True}
    assert extract_json('{"q": "escaped \\" quote }"}') == {"q": 'escaped " quote }'}
    for bad in ("", "no braces", "{unclosed", "[1, 2]"):
        with pytest.raises(ValueError):
            extract_json(bad)


# ---- call_json ---------------------------------------------------------------------------
async def test_call_json_parses_valid_reply():
    r = await call_json(MockProvider([GOOD]), "sys", "prompt", AgentTurn)
    assert r.ok and r.attempts == 1 and isinstance(r.value.action, Gather)
    assert r.value.messages[0].text == "heading to the forest"


async def test_call_json_retries_once_with_the_error_then_succeeds():
    p = MockProvider(["I think I'll gather wood!", GOOD])
    logs = []
    r = await call_json(p, "sys", "prompt", AgentTurn, log=lambda *a: logs.append(a))
    assert r.ok and r.attempts == 2 and len(p.calls) == 2
    assert "rejected" in p.calls[1][1] and "no JSON object" in p.calls[1][1]
    assert p.calls[1][1].startswith("prompt")
    assert [(ok, attempt) for _, ok, _, attempt in logs] == [(False, 0), (True, 1)]


async def test_call_json_reports_schema_errors_and_gives_up():
    bad = json.dumps({"action": {"type": "teleport"}})
    p = MockProvider([bad])
    r = await call_json(p, "sys", "prompt", AgentTurn)
    assert not r.ok and r.value is None and r.attempts == 2 and len(p.calls) == 2
    assert "action" in r.error
    too_many = json.dumps({"action": {"type": "rest"}, "messages": [{"channel": "group", "text": "x"}] * 3})
    assert not (await call_json(MockProvider([too_many]), "s", "p", AgentTurn, retries=0)).ok


async def test_quota_and_auth_errors_propagate_not_swallowed():
    with pytest.raises(QuotaExhausted):
        await call_json(MockProvider([QuotaExhausted("5-hour limit reached")]), "s", "p", AgentTurn)
    with pytest.raises(AuthError):
        await call_json(MockProvider([AuthError("login")]), "s", "p", AgentTurn)


def test_turn_schema_accepts_rest_without_messages():
    assert isinstance(AgentTurn.model_validate({"action": {"type": "rest"}}).action, Rest)


# ---- cache -------------------------------------------------------------------------------
async def test_cached_mode_second_call_is_served_from_cache():
    inner = MockProvider(["one", "two"])
    c = CachedProvider(inner, mode="cached")
    a, b = await c.complete("s", "p"), await c.complete("s", "p")
    assert (a.text, a.cache_hit, b.text, b.cache_hit) == ("one", False, "one", True)
    assert len(inner.calls) == 1
    assert (await c.complete("s", "other")).text == "two" and len(inner.calls) == 2


async def test_replay_mode_never_calls_model_and_misses_raise(tmp_path):
    path = tmp_path / "cache.db"
    rec = CachedProvider(MockProvider(["recorded"]), path, mode="cached")
    await rec.complete("s", "p")
    rec.close()
    inner = MockProvider(["SHOULD NOT BE USED"])
    rep = CachedProvider(inner, path, mode="replay")
    assert (await rep.complete("s", "p")).text == "recorded"
    with pytest.raises(CacheMiss):
        await rep.complete("s", "never seen")
    assert inner.calls == []


async def test_fresh_mode_always_calls_and_overwrites():
    inner = MockProvider(["v1", "v2", "v3"])
    c = CachedProvider(inner, mode="fresh")
    assert [(await c.complete("s", "p")).text for _ in range(2)] == ["v1", "v2"]
    c.mode = "replay"
    assert (await c.complete("s", "p")).text == "v2"  # latest sample is what replay sees


async def test_namespaces_isolate_samples():
    assert cache_key("m", "s", "p", "run1") != cache_key("m", "s", "p", "run2")
    assert cache_key("m", "s", "p") == cache_key("m", "s", "p")
    assert cache_key("m", "ab", "c") != cache_key("m", "a", "bc")  # no boundary collisions


def test_bad_mode_rejected():
    with pytest.raises(ValueError):
        CachedProvider(MockProvider(), mode="nope")


# ---- CLI output interpretation -----------------------------------------------------------
def cli_json(**kw):
    return json.dumps({"is_error": False, "result": '{"ok":1}', "duration_ms": 900, **kw})


def test_interpret_success_sums_cache_tokens():
    r = interpret(cli_json(usage={"input_tokens": 2, "cache_creation_input_tokens": 900,
                                  "cache_read_input_tokens": 10, "output_tokens": 9}), "", 0)
    assert (r.text, r.input_tokens, r.output_tokens, r.latency_ms) == ('{"ok":1}', 912, 9, 900)


def test_interpret_classifies_failures():
    err = lambda msg: json.dumps({"is_error": True, "result": msg})
    with pytest.raises(AuthError):
        interpret(err("Failed to authenticate: OAuth session expired"), "", 1)
    with pytest.raises(AuthError):
        interpret(err("Not logged in · Please run /login"), "", 1)
    with pytest.raises(QuotaExhausted):
        interpret(err("5-hour limit reached ∙ resets 3pm"), "", 1)
    with pytest.raises(QuotaExhausted):
        interpret(err("Claude AI usage limit reached"), "", 1)
    with pytest.raises(LLMError) as e:
        interpret("not json at all", "boom", 1)
    assert e.value.transient and not isinstance(e.value, (AuthError, QuotaExhausted))
    with pytest.raises(LLMError):
        interpret(cli_json(), "", 3)  # non-zero exit even with parseable output


# ---- CLI provider mechanics (subprocess faked) ---------------------------------------------
@pytest.fixture
def cli(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: "claude-fake")
    return ClaudeCLIProvider(concurrency=2, retries=2, backoff=0)


async def test_cli_concurrency_is_capped(cli):
    state = {"now": 0, "peak": 0}

    async def fake_run(system, prompt):
        state["now"] += 1
        state["peak"] = max(state["peak"], state["now"])
        await asyncio.sleep(0.02)
        state["now"] -= 1
        return cli_json(), "", 0

    cli._run = fake_run
    rs = await asyncio.gather(*(cli.complete("s", f"p{i}") for i in range(8)))
    assert len(rs) == 8 and state["peak"] == 2


async def test_cli_retries_transient_but_not_quota_or_auth(cli, monkeypatch):
    cli.backoff = 0
    n = {"c": 0}

    async def flaky(system, prompt):
        n["c"] += 1
        return (cli_json(), "", 0) if n["c"] == 3 else ("garbage", "", 1)

    cli._run = flaky
    assert (await cli.complete("s", "p")).text == '{"ok":1}' and n["c"] == 3

    n["c"] = 0

    async def quota(system, prompt):
        n["c"] += 1
        return json.dumps({"is_error": True, "result": "usage limit reached"}), "", 1

    cli._run = quota
    with pytest.raises(QuotaExhausted):
        await cli.complete("s", "p")
    assert n["c"] == 1


async def test_cli_gives_up_after_retries(cli, monkeypatch):
    cli.backoff = 0

    async def always_bad(system, prompt):
        return "garbage", "", 1

    cli._run = always_bad
    with pytest.raises(LLMError):
        await cli.complete("s", "p")


# ---- logging into the store ------------------------------------------------------------------
async def test_call_log_callback_can_write_llm_calls_table():
    from driftwood.config import load_scenario
    from driftwood.world import World

    store = Store()
    rid = store.create_run(World.new(load_scenario(), ["A"], seed=1))

    def log(resp, ok, error, attempt):
        store.log_llm_call(rid, 1, "A", "decide", cache_hit=bool(resp and resp.cache_hit),
                           input_tokens=resp.input_tokens, output_tokens=resp.output_tokens,
                           ok=ok, error=error)

    await call_json(MockProvider(["nope", GOOD]), "s", "p", AgentTurn, log=log)
    rows = store.db.execute("SELECT ok, error FROM llm_calls ORDER BY id").fetchall()
    assert [r["ok"] for r in rows] == [0, 1] and rows[0]["error"]
