# Phase 4 audit: first real day with 8 Haiku agents (seed 1)

Transcript of the tuned run: [audits/day1-tuned-transcript.txt](audits/day1-tuned-transcript.txt).

## Numbers (day 1 = 6 ticks + dusk reflections)
| | before tuning | after tuning |
|---|---|---|
| LLM calls | 56 | 56 |
| first-try invalid JSON | 0 (0%) | 0 (0%) |
| failed turns | 0 | 0 |
| private thoughts that mention the stray environment text | 0 | 0 |
| tokens in / out | 204k / 49k | 215k / 53k |
| wall time (4 parallel) | 2m08 | 2m25 |
| radio messages | 60 | 58 |

A full 7-day game is therefore roughly 1.5M input / 370k output tokens and about 15-20 minutes of wall time
(memories and beliefs grow the prompts a bit each day). Whether that fits a Pro window is untested.

## What worked
- Voices stay distinct and consistent for all 8 (Mara terse lowercase, Theo "okay okay okay", Elliot "for the
  record", Rosa blunt, Ama warm, Jun slang, Priya checking in, Viktor clipped).
- Real social dynamics emerged unprompted: tally politics, an agent admitting held-back gold, gossip, shifting
  trust and suspicions in the nightly reflections. Nobody was told to scheme.
- Agents reason from the incentives (seats, ballot, tie-break on contribution) without being told a strategy.

## Problems found and fixed
1. **Rules knowledge gap.** Agents did not know a build action adds at most 4 units, so one agent's honest
   "14 of 24" was read as a lie by half the camp. Now stated in the system prompt. (Without this the
   data would have measured confusion, not deception.)
2. **Pronoun drift.** The same agent was called her and his by different agents. Personas now carry pronouns,
   shown next to each name in the roster.
3. **Everyone talks every turn.** Telling agents silence is normal barely helped (60 -> 58 messages for 48 turns).
   Left as a tuning knob: if it matters, cap daytime messages at 1 or add a per-turn speak cost.
4. Night thoughts printed without names (cosmetic, fixed).

## Known quirks (not fixed on purpose)
- At dawn nearly everyone walks to the same place before anyone has claimed a job (they all see the same state).
  They sort it out within two ticks, which is itself a reasonable coordination result.
- Agents sometimes announce a plan in the past tense ("I'm adding my wood") before it resolves. The prompt now says
  actions are simultaneous, but expect the occasional unreliable report. That is realistic and worth keeping.
- One agent claimed to have been at the wreck before actually searching: small, plausibly deceptive, unverified.
