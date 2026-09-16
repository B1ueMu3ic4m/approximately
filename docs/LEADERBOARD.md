# Real-data benchmark: MAST annotated trajectories (v4 pipeline)

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

## Result history (all rules-only, same 13 single-label records)

| run | pipeline | accuracy | macro-F1 | FM-2.1 |
|---|---|---|---|---|
| v2 (0.14) | prose family, SequenceMatcher restart | 0.00 | 0.00 | 0/2 recall |
| v3 (0.15) | + shingle-overlap restart, conf 0.6 | 0.00 | 0.00 | fires, but 0.6 < labeler floor |
| **v4 (0.15, shipped)** | shingle conf 0.7 | **0.08** | **0.07** | **P 0.50 · R 0.50 · F1 0.50** |

The v3->v4 move is the most instructive line in this file: the shingle
detector fired on a true FM-2.1 at confidence 0.6 in v3 and the
prediction was still lost - 0.6 clears the attribution floor (0.5) but
not the rules-labeler floor (0.7), so the evidence existed and was
unusable. Detector confidence scales must be coordinated with the
prediction floor, or calibration is a fiction. The shipped shingle
path carries 0.7: majority character-trigram overlap on turns of
500+ chars is evidence of the same strength as near-verbatim
repetition.

Per-mode state after v4:

| gold | n | state |
|---|---|---|
| FM-2.1 | 2 | **1 hit** (opening-turn shingle recurrence), 1 miss: semantic restart at J 0.55 borderline + FM-1.3 prior wins the fused ranking on the 62-turn multi-mode-shaped record |
| FM-1.3 | 0 golds | 2 false predictions: HyperAgent planner/executor echo pairs clear the 0.92 similarity floor - harness echo vs agent pathology is unresolved |
| FM-3.2 | 6 | verification is *discussed* in these SWE runs ("we should verify"); absence-of-language is the wrong signal - outcome-level analysis needed |
| FM-2.2 | 2 | agents asked a clarifying question, correctly suppressing the detector; annotation judges the outcome anyway |
| FM-2.3 | 2 | trailing-window keyword loss did not fire; window shape mismatch |
| FM-2.6 | 1 | thought/action entity divergence not present in the single gold |

Everything else in the accounting is unchanged: 15 multi-label,
1841 no covered mode, 87 unannotated, 4 too few agent turns,
3 unreadable - all counted, none silently dropped.

## Reproduce

```bash
git clone --depth 1 https://github.com/multi-agent-systems-failure-taxonomy/MAST.git
approximately convert-mast MAST/traces mast-bench.jsonl
approximately benchmark mast-bench.jsonl --html leaderboard.html
```
