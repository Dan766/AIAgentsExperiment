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
