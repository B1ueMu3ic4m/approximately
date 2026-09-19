# Real-data benchmark: MAST annotated trajectories (v6 pipeline)

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

| run | pipeline | accuracy | macro-F1 | FM-2.1 | FM-1.3 FP |
|---|---|---|---|---|---|
| v2 (0.14) | prose family, SequenceMatcher restart | 0.00 | 0.00 | 0/2 | 0 |
| v3 (0.15) | + shingle-overlap restart, conf 0.6 | 0.00 | 0.00 | fires, below labeler floor | 2 |
| v4 (0.15) | shingle conf 0.7 | 0.08 | 0.07 | P .50 R .50 F1 .50 | 2 |
| v5 (0.17) | + routing-placeholder filter | 0.08 | 0.07 | P .50 R .50 F1 .50 | 1 |
| **v6 (0.17, shipped)** | + restart-owns-opening-cycle | **0.08** | **0.08** | **P .50 R .50 F1 .50** | **0** |

v5 -> v6: a repetition cycle **anchored at the opening turn** is a
trajectory restart (the agent re-runs the same approach from the
start), not an independent repetition failure - the restart detector
owns that signal, and ProseRepeat now yields it (specificity
precedence). FM-1.3's false predictions went to zero; FM-2.1 holds
P 0.50 / R 0.50 / F1 0.50.

## Multi-label evaluation (v0.29): 27 records, set-based P/R/F1

Single-label evaluation threw away 15 multi-mode golds. `convert-mast
--multi-label` + `benchmark --multi-label` now score them honestly
(predicted set = all modes the fusion reports at confidence >= 0.5;
sample-averaged set P/R/F1, plus per-mode pooled counts). Same corpus,
same hygiene:

```
converted 27 multi-label records | FM-2.1 x13, FM-3.2 x11, FM-2.3 x7,
FM-1.3 x7, FM-2.2 x5, FM-2.6 x2, FM-1.2 x4, FM-2.4 x4, FM-2.5 x2, ...
```

| mode | precision | recall | F1 |
|---|---|---|---|
| **FM-2.1 restart** | **0.93** | **1.00** | **0.96** |
| FM-1.3 repetition (v0.38 cycle) | 1.00 [0.57,1.00] | 0.71 [0.36,0.92] | 0.83 |
| FM-3.2 outcome-verify (v0.31) | 0.54 | 0.64 | 0.58 |
| FM-2.6 thought/action (v0.30 guards) | 0.33 | 0.50 | 0.40 |
| others (FM-1.2/2.2/2.3/2.4/2.5/3.1) | 0 | 0 | 0 |

Since v0.35 the CLI prints 95% Wilson intervals beside every P and R
(FM-2.1's P 0.93 is [0.69, 0.99] — strong, but n=27). Read of it: the
shingle restart detector is *strong* on real annotated
data (13/13 recall, one false positive across 27 runs); repetition has
frontier-grade precision but missed echo variants — v0.38's cycle-grade
detector reads the repeated tool *sequence* instead of exact
fingerprints (multi-agent inner loops evolve their args every turn, so
the sequence is the invariant), lifting recall 0.14 → 0.71 (tp 1 → 5)
with zero new false positives; the thought/action
divergence heuristic over-fired on log-style traces (14 false
positives, precision 0.07) until v0.30's action-continuity guards —
prompt-scaffold echo, entity-token continuity (path/stem/bare-name
variants), thought-context continuity — cut it to 2 (precision 0.33,
F1 0.40, recall unchanged); v0.31 added outcome-level verification
analysis (completion claim + zero outcome signals in the record =
unchecked claim), the first nonzero FM-3.2 score. Corpus-level sample
precision 0.30 → 0.55, F1 0.25 → 0.46 across v0.30+v0.31+v0.38. FM-3.1
("claiming done while it is not true") remains open — it needs
ground truth about the claim being false, which no record-level rule
can have. Numbers are n=27 — directional, not decisive; bracketed
intervals are Wilson 95% score intervals on the pooled counts.

## The synthetic regression fixture (v0.51)

`docs/mast-bench-synth.jsonl` — 180 records generated by
`scripts/make_synth_corpus.py` (seeded, byte-identical on
regeneration) — is a **canary, not a benchmark**: every scenario
plants its failure mode by construction, so the detectors score
1.00 across the measured modes (FM-1.3/2.1/2.6/3.2) and
`bench_gate.py --synth` fails CI the moment any of them drops below
0.95. Use it to catch detector regressions with tight intervals;
never quote its numbers as real-world performance — the gold-corpus
section above (n=27) is the only real-data evidence, and FM-2.3/
FM-3.1 are deliberately absent from the fixture (no record-level
signal / no prose detector).

## The calibration lesson (v3 -> v4, kept for the record)

The shingle detector fired on a true FM-2.1 at confidence 0.6 in v3
and the prediction was still lost - 0.6 clears the attribution floor
(0.5) but not the rules-labeler floor (0.7), so the evidence existed
and was unusable. Detector confidence scales must be coordinated with
the prediction floor, or calibration is a fiction. The shipped shingle
path carries 0.7: majority character-trigram overlap on turns of
500+ chars is evidence of the same strength as near-verbatim
repetition.

## Per-mode state after v6

| gold | n | state |
|---|---|---|
| FM-2.1 | 2 | **1 hit** (opening-turn shingle recurrence); 1 miss: semantic restart at J 0.55 borderline loses the fused ranking to a co-occurring signal |
| FM-1.3 | 0 golds | **0 false predictions** - placeholder filter + restart precedence cleaned both |
| FM-3.2 | 6 | verification is *discussed* in these SWE runs; the annotation judges whether the *outcome* was verified. All 6 golds contain both verification and execution language - regex cannot cross that semantic gap on n=6 without gold-fitting, so outcome-level analysis is **deliberately deferred** |
| FM-2.2 | 2 | agents asked a clarifying question, correctly suppressing the detector |
| FM-2.3 | 2 | diagnosed (v0.25): task keywords persist in *every* turn of both golds — the annotated derailment is goal-progress drift, not vocabulary drift; keyword-based windows are structurally inadequate and a progress-level feature is deferred rather than fitted on n=2 |
| FM-2.6 | 1 | thought/action entity divergence not present in the single gold |

Conversion accounting (unchanged, everything counted):
15 multi-label, 1841 no covered mode, 87 unannotated, 4 too few
agent turns, 3 unreadable.

## Reproduce

```bash
git clone --depth 1 https://github.com/multi-agent-systems-failure-taxonomy/MAST.git
approximately convert-mast MAST/traces mast-bench.jsonl
approximately benchmark mast-bench.jsonl --html leaderboard.html
```
