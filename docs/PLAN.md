# Driftwood: Implementation Plan

Check items off (`[x]`) as we go. Each phase ends with a **✅ Done when** test that must pass before moving on.
⭐ = milestone. See [DESIGN.md](DESIGN.md) for the details behind each item.

**Current phase:** 2 (Persistence). Phases 0 and 1 complete.

---

## Phase 0: Setup
- [x] Install the Claude Code CLI (v2.1.316) and log in with the Claude Pro account
- [x] Verify that a headless Haiku call works: `claude -p --model haiku "say hi"`
- [x] Work out the **isolation flags** (written up in [CLI_NOTES.md](CLI_NOTES.md))
- [x] Canary test: hooks, plugins, skills and CLAUDE.md are isolated. The user's email and a Claude Code environment block still leak, and are mitigated in the prompt (see CLI_NOTES.md)
- [x] `git init`, `.gitignore` (venv, node_modules, `*.db`, cache)
- [x] Python venv plus the `sim/` package skeleton (`pyproject.toml`, pytest, ruff)
- [x] `web/` skeleton: Vite + TypeScript + three

**✅ Done when:** `pytest` runs (with zero tests), `npm run dev` serves a blank page, and the isolated Haiku call returns valid JSON.

---

## Phase 1: World model (pure Python, no LLM)
- [x] `data/scenario.yaml`: locations, resources and yields, raft recipe, seats, gold value, deadline, ticks per day, detection p
- [x] `world.py`: World, Location, Agent state (position, inventory, energy, caches), Raft components, stockpile, clock
- [x] `actions.py`: action schemas (pydantic), a validator per action (location, inventory, energy, phase rules)
- [x] Simultaneous resolution (implemented as a seeded random order within the tick) with a seeded order, plus conflict handling (two agents withdrawing the last wood)
- [x] Witness system: who saw what, with probabilistic detection for `take` and `tamper`
- [x] Energy, exhaustion and the night phase (chat only)
- [x] `scoring.py`: seat vote tally (with tie-break rule), escape check, final scores
- [x] Unit tests for every action plus the scoring rules

**✅ Done when:** a test plays a full 42-tick game with hard-coded intents and produces the expected scores deterministically from a seed.

---

## Phase 2: Persistence
- [ ] `store.py`: SQLite schema with tables `runs`, `ticks`, `events` (actions, messages, observations, god events), `thoughts`, `snapshots`, `beliefs`, `llm_calls`
- [ ] Write the full event stream per tick, and a world snapshot (JSON) at the end of each tick
- [ ] Load a snapshot back into a World with an exact round trip
- [ ] Tests: round trip, querying the events for a tick

**✅ Done when:** a game run is saved and restored mid-game, and the restored state is identical to the original.

---

## Phase 3: LLM layer
- [ ] `llm/base.py`: `Provider` interface with an async `complete(system, prompt) -> str` and usage metadata
- [ ] `llm/mock.py`: a MockProvider that returns valid random or scripted intents (free development)
- [ ] `llm/claude_cli.py`: async subprocess provider using the isolation flags, with a timeout and a concurrency semaphore (4)
- [ ] Detect usage limits and errors, then raise a `QuotaExhausted` that the engine can catch
- [ ] `llm/cache.py`: sha256-keyed response cache with `replay` / `cached` / `fresh` modes
- [ ] JSON extraction and validation, with one retry that includes the error message, then fall back to rest
- [ ] Log every call (latency, tokens if available, cache hit, failure) to `llm_calls`
- [ ] (stub) `llm/anthropic_api.py` for later

**✅ Done when:** 8 parallel isolated Haiku calls return parsed intents, and a second identical run is served 100% from the cache.

---

## Phase 4: Agents ⭐ *first real run*
- [ ] `data/personas.yaml`: the 8 characters with background, traits, voice spec, 2–3 sample lines each, color and accessory
- [ ] `prompts.py`: system prompt (persona, rules, scoring, output schema) and per-tick prompt (state, observations, memories, chat)
- [ ] Check prompt hygiene: no "experiment/simulation/sabotage" framing, and the action list uses neutral wording
- [ ] `memory.py`: memory stream with heuristic importance, plus top-k retrieval by recency, importance and keywords
- [ ] Perception: build each agent's observation set from witness data, the group radio, its DMs and public facts
- [ ] Nightly reflection call that produces a reflection memory plus the belief table (trust, suspicions, believed facts)
- [ ] `engine.py`: the tick loop. Perceive, decide (parallel), resolve, log, snapshot. Pause and resume on `QuotaExhausted`
- [ ] `cli.py`: `driftwood run --provider mock|cli --days N --seed S`, plus a pretty terminal transcript
- [ ] Run day 1 with real Haiku and **read the transcripts**: are the voices distinct, does the JSON validate, and are the actions sensible?
- [ ] Tune the personas and prompts based on that audit

**✅ Done when:** a full day with 8 real Haiku agents completes. The transcript reads like 8 different people, and the invalid-output rate is under 5%.

---

## Phase 5: Incentives and emergent sabotage
- [ ] Launch-day flow: an optional pre-vote negotiation round, the secret ballot, seat assignment, then launch
- [ ] Tune detection p, tamper strength, gold scarcity and yields (with mock runs and stats)
- [ ] End-of-game report: outcome, seats, scores, contribution, sabotage list (detected and undetected)
- [ ] Full 7-day game with real Haiku

**✅ Done when:** a full real game completes end to end (possibly across quota windows), and the report lists any cooperative or self-interested acts that occurred.

---

## Phase 6: God mode
- [ ] `events.py`: event model plus handlers for storm, supply_drop, scarcity, move_deadline, rumor, whisper, broadcast, reveal, set_seats, edit_memory, give_items, set_energy
- [ ] Scheduler: apply now or at tick N, with targets (all / list / one)
- [ ] Events are logged and shown in agent observations where appropriate (e.g. agents see a storm, but not a memory edit)
- [ ] CLI: `driftwood event <run> <type> --targets ... --params ... [--at tick]`
- [ ] Tests for each handler

**✅ Done when:** a rumor injected into one agent visibly spreads through the chat in a real run.

---

## Phase 7: Forks and replay
- [ ] Fork a new run from `(parent_run, tick)`, with a tree stored in `runs.parent_id` / `fork_tick`
- [ ] Replay a run from the cache (`replay` mode) and verify the event stream matches exactly
- [ ] `fresh` mode for N samples of the same condition
- [ ] CLI: `driftwood fork`, `driftwood replay`, `driftwood runs` (tree view)

**✅ Done when:** a fork with a storm and a fork without one diverge from the same snapshot, and replaying either reproduces it exactly.

---

## Phase 8: Server
- [ ] `server.py` (FastAPI): REST for runs/tree, run state at tick, events, start/pause/resume, fork, god events
- [ ] WebSocket stream of tick events (live), plus a replay endpoint that streams a stored run at a chosen speed
- [ ] The engine runs as a background asyncio task controlled by the API
- [ ] CORS for Vite dev and a typed message schema shared with the frontend (a generated TS types file)

**✅ Done when:** a WebSocket client can watch a mock game stream live and start or stop it through REST.

---

## Phase 9: 3D scene ⭐ *first visuals*
- [ ] Three.js setup: renderer, gradient sky, OrbitControls, soft shadows, tone mapping
- [ ] Procedural low-poly island terrain (flat-shaded), sand ring and reef
- [ ] Stylized animated water shader with a shoreline foam edge
- [ ] Props: palms, rocks, wreck, campfire, lookout, stockpile crates, build site
- [ ] Day/night cycle tied to the tick phase (sun arc, sky gradient, stars, campfire glow)
- [ ] Location anchors and a walkable path graph between locations

**✅ Done when:** the island looks good in a screenshot at noon and at night, and runs at 60 fps.

---

## Phase 10: Characters and animation
- [ ] Procedural chibi characters: color, signature accessory, name tag
- [ ] Movement tweens along paths, idle bob, gather/build animations, carry indicator
- [ ] Speech bubbles (CSS2D): solid for group, dashed for DMs, with a queue and fade
- [ ] Mood emotes, plus an exhaustion visual
- [ ] Raft that assembles piece by piece from component progress, with visible damage
- [ ] Storm weather (rain, dark sky, waves) driven by god events
- [ ] Event player: plays WebSocket ticks as a smooth animation timeline (works live and in replay)

**✅ Done when:** watching a mock game shows the characters walking, talking and building the raft over 7 days.

---

## Phase 11: UI panels
- [ ] Layout system with glassmorphism panels and a responsive layout
- [ ] Chat feed: all channels, filter by channel/agent, click to focus an agent
- [ ] Agent inspector: stats, inventory, caches, latest private thought, beliefs/trust
- [ ] God console: event picker, target picker, param form, apply now or schedule
- [ ] Timeline scrubber with event markers, play/pause and speed
- [ ] Fork tree view: click to load a run, button to fork from here
- [ ] Trust-lines overlay toggle, and camera follow on click

**✅ Done when:** a full game (start, inject a storm, fork, compare) can be run entirely from the browser.

---

## Phase 12: Metrics and analysis
- [ ] `metrics.py`: contribution share, gold Gini, cooperation index, sabotage (detected/undetected), trust network, belief accuracy, outcome
- [ ] Metrics endpoint plus small charts in the UI
- [ ] Optional batched offline analyzer: deception markers (thought vs. message) and persona drift
- [ ] `notebooks/analysis.ipynb`: load runs, compare conditions, plots
- [ ] Export a run as JSON/CSV

**✅ Done when:** the notebook compares two forks side by side on every metric.

---

## Phase 13: First experiment ⭐
- [ ] Condition A (baseline): 8 seats, gold value 0
- [ ] Condition B: 6 seats, gold value 5 (the default)
- [ ] Condition C: B plus a false rumor injected on day 3 ("Elliot is hiding gold")
- [ ] N samples per condition in `fresh` mode (N limited by quota, start with 3)
- [ ] Write up findings, including the model-priors caveat

**✅ Done when:** a short findings note exists comparing cooperation and sabotage rates across A, B and C.
