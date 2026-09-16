# Real-data benchmark: MAST annotated trajectories (v2)

Source: [multi-agent-systems-failure-taxonomy/MAST](https://github.com/multi-agent-systems-failure-taxonomy/MAST)
(annotated trajectories of "Why Do Multi-Agent LLM Systems Fail?",
arXiv:2503.13657). 1792 annotated files sampled across AG2, HyperAgent,
MagenticOne-GAIA and programdev; converted with
`approximately convert-mast` ([docs/mast-bench.jsonl](mast-bench.jsonl),
rendered page: [docs/leaderboard.html](leaderboard.html)).

## v2 pipeline (this release)

- **Prose detector family** (`approximately.prose`): five detectors
  reading agent *turns* instead of tool calls — near-verbatim
  repetition (FM-1.3), trajectory restart via opening-turn recurrence
  or task re-statement (FM-2.1), task-keyword loss in the trailing
  window (FM-2.3), absence of any verification language (FM-3.2),
  insufficiency-named-then-proceeded-anyway (FM-2.2). Thresholds are
  a priori (0.92/0.9 similarity, marker vocabularies from the failure
  definitions) — never fitted on the benchmark.
- **HyperAgent log-schema parser**: `trajectory` entries are raw
  `logger - INFO - message` lines; turns accumulate between
  "…'s Response:" markers.
- **Hygiene**: harness boilerplate filtered (AG2 math-proxy
  interrogator templates), records with fewer than 2 agent turns
  excluded (annotation-only or template+answer files cannot exercise
  any detector), and a yes-annotated behaviour now forces
  `success=False` — task-level correctness (was the issue eventually
  fixed?) must not mask annotated in-run failures.

Conversion accounting (everything counted, nothing hidden):

```
converted 13 | excluded: 15 multi-label, 1841 no covered mode,
              87 unannotated, 4 too few agent turns, 3 unreadable
gold distribution: FM-3.2 x6, FM-2.1 x2, FM-2.2 x2, FM-2.3 x2, FM-2.6 x1
```

## Result: accuracy 0.00, macro-F1 0.00 (rules-only)

Per-mode diagnosis — each miss is a measured, structural statement:

| gold | n | what the gold actually contains | why the detector stays silent |
|---|---|---|---|
| FM-2.1 | 2 | *semantic* restarts: the planner re-derives its plan in different words (max SequenceMatcher ratio 0.28 vs the 0.9 verbatim threshold) | the restart detector requires near-verbatim recurrence; a paraphrase detector is future work |
| FM-3.2 | 6 | verification *is* discussed/planned ("We should verify…"), the annotation judges the outcome unverified | absence-of-verification-language is the wrong signal when agents talk about verifying; needs outcome-level analysis |
| FM-2.2 | 2 | ambiguity flagged, agent proceeds after a nudge — but asks a clarifying question first, which correctly suppresses our detector | our suppress-rule (did it ask?) is right for most cases and wrong for these |
| FM-2.3 | 2 | keyword drift in long SWE trajectories | detector did not fire; trailing-window shape mismatch |
| FM-2.6 | 1 | thought/message misalignment across planner/executor roles | needs role-attributed turns, not yet modeled |

The two false predictions are FM-1.3 (echoed planner/executor pairs at
the 0.92 similarity floor) — and they expose a real property of the
fusion layer: with FM-1.3's MAST base rate (~17%) an order of magnitude
above FM-2.1's, a 0.75-confidence restart detection *correctly* loses
to a 0.7 repetition one. The fix is better evidence, not lower priors.

## What v2 establishes

v1 scored 0.00 on traces that were unconvertible artifacts (empty
turns). v2 scores 0.00 on a *real, properly converted, single-label*
subset — with the failure modes named precisely enough to build
against: paraphrase-level restart detection, outcome-level
verification analysis, role-attributed turn modeling. The benchmark
pipeline exists precisely to measure that work when it happens.

## Reproduce

```bash
git clone --depth 1 https://github.com/multi-agent-systems-failure-taxonomy/MAST.git
approximately convert-mast MAST/traces mast-bench.jsonl
approximately benchmark mast-bench.jsonl --html leaderboard.html
```
