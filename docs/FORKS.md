# Phase 7: forks, replay and exact reproduction (real Haiku data from game 1)

Output of the acceptance run: [audits/phase7-fork-replay-output.txt](audits/phase7-fork-replay-output.txt).

## How it works
- `driftwood fork RUN --tick T [--event storm --params ...]` copies the parent's history up to tick T into a new run
  (snapshots, events, thoughts, beliefs), applies the optional god event at T, and runs the branch. Because history is
  copied, every tool (export, report, viewer, load-at-any-tick) works on a fork unchanged.
- Forks inherit the parent's LLM cache namespace, so a branch only pays for calls whose prompts actually differ.
  A control branch (no event) is therefore a **free, exact copy** of its parent.
- `--samples N` runs N independent branches in `fresh` mode, each in its own cache namespace, so sampling noise can be
  measured and each sample can still be replayed on its own later.
- `driftwood replay RUN` re-runs a run (from its fork point) into a new run using only the cache and compares it with
  the original tick by tick: world, every agent's memory and beliefs, every event and thought.
- `driftwood runs` shows the fork tree and `driftwood compare A B` shows where two runs diverge and how the outcomes differ.

## Acceptance results (game 1, forked at tick 24 = day 5 dawn)
| | calls | cache hits | outcome |
|---|---|---|---|
| parent #1 | 406 (recorded) | | launched; seats Mara Viktor Priya Rosa Ama Theo |
| control fork #3 (no event) | 180 | **180** | **identical worlds to the parent** (0 model calls) |
| storm fork #2 (severity 0.5, -20 energy) | 177 | 113 | diverges at tick 24; launched; seat order shifted; Mara, Priya, Viktor +5 points (gold) |
| replay of #2, #3 and #1 | | all | **IDENTICAL to the original** each time (0 model calls) |

The storm barely mattered in this seed: the group had slack, rebuilt, and finished. One seed is an anecdote, not a
finding; this is the machinery for measuring it properly (control vs treatment, N samples each).

## A reproducibility bug the real data caught
The first attempt at this test showed the **control fork diverging from its parent** (44 of 176 cache hits, first
different world at tick 31). Cause: after game 1 I raised the message length limit from 600 to 900 characters. In the
original run Ama's tick-28 reply had an over-600 message, was rejected and retried; under the new limit the same cached
reply was accepted outright, so Ama said something different, the following prompts changed, and the cache stopped
matching. **Changing any validation rule after a run silently breaks exact replay of that run.**

Fix: output limits (`turn.LIMITS`) are now recorded on every run (`runs.rules`) and re-applied on resume, fork and
replay. Two regression tests reproduce the failure (with and without the recorded rules). Game 1 predates the column, so
its rules were set by hand to `{"message_chars": 600}`.

**Rule of thumb for any future change:** if it can change whether a model reply is accepted, or the text of any
prompt, it either belongs in the run's recorded rules or it invalidates replay of older runs (cache misses, or
silently different behaviour). Prompt-text changes simply miss the cache, which is safe; acceptance-rule changes are
the dangerous kind because they can still hit the cache and quietly take a different path.

## Not yet verified with a real model
`--samples N` in `fresh` mode is covered by tests using a deliberately non-deterministic fake model, not by a live run
(each real sample costs a full rerun of the remaining ticks, about 180 calls).
