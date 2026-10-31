import hashlib
import sqlite3
import time
from pathlib import Path

from .base import CacheMiss, LLMResponse, Provider

MODES = ("replay", "cached", "fresh")


def cache_key(model: str, system: str, prompt: str, namespace: str = "") -> str:
    h = hashlib.sha256()
    for part in (model, system, prompt, namespace):
        h.update(part.encode("utf-8"))
        h.update(b"\0")
    return h.hexdigest()


class CachedProvider:
    """Wraps a provider with a persistent response cache.

    replay: only recorded responses, a miss raises CacheMiss (exact reproduction of a past run).
    cached: use the cache when it hits, otherwise call the model and record.
    fresh:  always call the model and record (overwriting), to sample variance. Use a distinct
            `namespace` per sample so each sample can later be replayed on its own.
    """

    def __init__(self, inner: Provider, path: str | Path = ":memory:", mode: str = "cached",
                 namespace: str = ""):
        if mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}")
        self.inner, self.mode, self.namespace = inner, mode, namespace
        self.model = inner.model
        self.last_key: str | None = None
        self.db = sqlite3.connect(str(path))
        self.db.execute("CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, text TEXT NOT NULL,"
                        " input_tokens INTEGER, output_tokens INTEGER, created REAL NOT NULL)")

    def key(self, system: str, prompt: str) -> str:
        return cache_key(self.model, system, prompt, self.namespace)

    def lookup(self, key: str) -> LLMResponse | None:
        row = self.db.execute("SELECT text, input_tokens, output_tokens FROM cache WHERE key = ?",
                              (key,)).fetchone()
        return LLMResponse(row[0], row[1], row[2], 0, cache_hit=True) if row else None

    async def complete(self, system: str, prompt: str) -> LLMResponse:
        key = self.last_key = self.key(system, prompt)
        if self.mode != "fresh":
            hit = self.lookup(key)
            if hit:
                return hit
            if self.mode == "replay":
                raise CacheMiss(f"no recorded response for key {key[:12]} (replay mode)")
        resp = await self.inner.complete(system, prompt)
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO cache VALUES (?,?,?,?,?)",
                            (key, resp.text, resp.input_tokens, resp.output_tokens, time.time()))
        return resp

    def close(self):
        self.db.close()
