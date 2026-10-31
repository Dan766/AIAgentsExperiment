# Claude CLI isolation notes (Phase 0 findings, CLI v2.1.316)

Agent calls use the Claude Code CLI on the Pro login (OAuth). Verified working command:

```
claude -p --model haiku --system-prompt "<persona+rules>" --tools "" --setting-sources "" \
  --strict-mcp-config --disable-slash-commands --no-session-persistence --output-format json "<prompt>"
```
Run it with a neutral cwd (an empty temp dir), never inside a project.

- Latency about 5s per call; the first call writes ~900 tokens to the prompt cache.
- JSON output: `result` holds the model text, `usage` the tokens, `is_error` / `terminal_reason` the failures.
  Auth failure shows as `is_error: true`, `result: "Failed to authenticate..."`.
- **Isolated (verified by canary):** user hooks (vibe-claude), plugins, skills, CLAUDE.md, memory, MCP.
- **Still leaks (cannot be removed on OAuth):** the user's email in a system-reminder, and a Claude Code
  environment block (cwd, platform, "Bash/PowerShell tool available", date, model name).
  - `--bare` and `CLAUDE_CODE_SIMPLE=1` strip it but disable OAuth ("Not logged in"), so they are unusable here.
  - `--exclude-dynamic-system-prompt-sections` only moves the block into the first user message.
  - **Mitigation:** the system prompt says the character is a person, and that any environment, platform,
    email or tool info is noise to be ignored. Verified in-character with Haiku.
  - Residual risk: private `thought` fields sometimes mention the noise ("environment details are irrelevant").
    Phase 4 audit: scan thoughts for these words, and flag them in the logs.
- Do not use `--bare` unless switching to an API key.

## Provider implementation (Phase 3)
- `ClaudeCLIProvider` runs `claude.cmd` (the npm shim; plain `claude` is a PowerShell script on Windows) with the
  prompt on **stdin** and the system prompt via `--system-prompt-file`, from an empty scratch dir.
- Measured: 8 parallel agent turns with concurrency 4 took ~15s wall (2 waves of ~5-7s), 8/8 valid JSON first try.
  A 42-tick game is therefore about 42 x 15s ≈ 10 minutes of wall time plus reflections.
- Errors: auth and usage-limit text are classified into `AuthError` / `QuotaExhausted` (no retry);
  anything else is retried with backoff. The exact quota wording is a regex guess (`QUOTA_RE`), so check
  it the first time a real limit is hit.
