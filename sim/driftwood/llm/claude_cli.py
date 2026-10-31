"""Provider that shells out to the Claude Code CLI so calls run on the user's Pro login.

Isolation flags and the known context leaks are documented in docs/CLI_NOTES.md. Never add --bare:
it disables the OAuth login this provider relies on.
"""
import asyncio
import hashlib
import json
import re
import shutil
import tempfile
import time
from pathlib import Path

from .base import AuthError, LLMError, LLMResponse, QuotaExhausted

QUOTA_RE = re.compile(r"(usage|rate|5-hour|weekly|session|opus) limit|limit reached|quota|too many requests",
                      re.I)
AUTH_RE = re.compile(r"authenticat|not logged in|/login|oauth|invalid api key|unauthori[sz]ed", re.I)

ISOLATION_FLAGS = [
    "-p", "--output-format", "json", "--tools", "", "--setting-sources", "",
    "--strict-mcp-config", "--disable-slash-commands", "--no-session-persistence",
]


def interpret(stdout: str, stderr: str, returncode: int) -> LLMResponse:
    """Turn raw CLI output into a response, or raise the matching error."""
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        data = None
    text = (data or {}).get("result") if data else None
    blob = f"{text or ''} {stderr} {stdout if data is None else ''}"
    if data is None or data.get("is_error") or returncode != 0:
        if QUOTA_RE.search(blob):
            raise QuotaExhausted(blob.strip()[:300])
        if AUTH_RE.search(blob):
            raise AuthError(blob.strip()[:300])
        raise LLMError(f"CLI failed (rc={returncode}): {blob.strip()[:300]}", transient=True)
    usage = data.get("usage") or {}
    return LLMResponse(
        text=text or "",
        input_tokens=(usage.get("input_tokens") or 0) + (usage.get("cache_creation_input_tokens") or 0)
        + (usage.get("cache_read_input_tokens") or 0),
        output_tokens=usage.get("output_tokens"),
        latency_ms=int(data.get("duration_ms") or 0),
    )


class ClaudeCLIProvider:
    def __init__(self, model: str = "haiku", concurrency: int = 4, timeout: float = 120.0,
                 retries: int = 2, backoff: float = 1.0, exe: str | None = None):
        self.model = model
        self.timeout = timeout
        self.retries = retries
        self.backoff = backoff
        self.exe = exe or shutil.which("claude.cmd") or shutil.which("claude")
        if not self.exe:
            raise LLMError("claude CLI not found on PATH")
        self._sem = asyncio.Semaphore(concurrency)
        # Run from an empty scratch dir so no project CLAUDE.md or settings are discovered.
        self._dir = Path(tempfile.mkdtemp(prefix="driftwood-cli-"))

    def _system_file(self, system: str) -> Path:
        path = self._dir / f"sys-{hashlib.sha256(system.encode()).hexdigest()[:16]}.txt"
        if not path.exists():
            path.write_text(system, encoding="utf-8")
        return path

    async def _run(self, system: str, prompt: str) -> tuple[str, str, int]:
        proc = await asyncio.create_subprocess_exec(
            self.exe, *ISOLATION_FLAGS, "--model", self.model,
            "--system-prompt-file", str(self._system_file(system)),
            cwd=self._dir, stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(prompt.encode("utf-8")), self.timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise LLMError(f"CLI timed out after {self.timeout}s", transient=True)
        return out.decode("utf-8", "replace"), err.decode("utf-8", "replace"), proc.returncode

    async def complete(self, system: str, prompt: str) -> LLMResponse:
        last: LLMError | None = None
        for attempt in range(self.retries + 1):
            async with self._sem:
                start = time.monotonic()
                try:
                    out, err, rc = await self._run(system, prompt)
                    resp = interpret(out, err, rc)
                    resp.latency_ms = resp.latency_ms or int((time.monotonic() - start) * 1000)
                    return resp
                except LLMError as e:
                    if not e.transient:
                        raise
                    last = e
            await asyncio.sleep(self.backoff * 2 ** attempt)  # backoff outside the semaphore
        raise last
