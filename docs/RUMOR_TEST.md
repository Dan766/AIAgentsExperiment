# Phase 6 acceptance test: does an injected rumor spread? (real Haiku agents, seed 2, days 1-3)

Both runs share one cache, so the first 8 ticks are identical and the only difference is the rumor.
Transcript of run 2: [audits/rumor-test2-transcript.txt](audits/rumor-test2-transcript.txt).

## Run 1: a false rumor to Theo ("Elliot has been hiding gold behind the wreck")  -> did NOT spread
Delivery worked (it was in Theo's tick-8 prompt and memory, and nobody else had it). Theo never acted on it: he was
busy confessing his own hidden gold, and his private thoughts for ticks 8-13 never mention it. Nobody repeated it.
**Lesson:** a rumor only travels if its recipient has a reason to use it.

## Run 2: a specific sighting to Priya ("Elliot was seen at dusk behind the wreck carrying a heavy bag ...")  -> spread
- Priya repeated it on the group radio on her next turn.
- Rosa, Ama and Viktor then repeated the question ("What was in the bag?") on the group radio across ticks 13-17.
- By the last snapshot all 8 agents held it in memory (Priya via the injection, the other 7 via her broadcast).
- Priya later DMed Elliot "I saw you near the wreck at dusk with a heavy bag": she had only heard a rumor, yet restated
  it as first-hand witness. Hearsay hardening into testimony is exactly the belief-distortion this sandbox should measure.
- Elliot never answered. Whether he gets voted off is not covered by this 3-day test.

## What this tells us about experiment design
- Pick the recipient on purpose: the agent who publicly checks facts (here Priya) is a far better seed than one who is
  preoccupied. Injection point is an independent variable.
- A concrete, checkable claim ("heavy bag, nothing on the pile") works better than a vague one.
- The event applied at tick 9 in run 2 (queued after the early cached ticks had already replayed), which is expected:
  an event with no matching tick fires at the next tick start.
