# Real-data benchmark: MAST annotated trajectories (v1)

Source: [multi-agent-systems-failure-taxonomy/MAST](https://github.com/multi-agent-systems-failure-taxonomy/MAST)
(the annotated-trajectory release of "Why Do Multi-Agent LLM Systems Fail?",
arXiv:2503.13657) — 463 annotated trace files sampled across AG2,
HyperAgent, MagenticOne-GAIA and programdev, converted with
`approximately convert-mast` (commit the JSONL: [docs/mast-bench.jsonl](mast-bench.jsonl),
rendered page: [docs/leaderboard.html](leaderboard.html)).

## Conversion honesty rules

1. Only annotation behaviours with a matching approximately detector are
   converted (10 of the 14 modes; FM-1.1 / FM-1.4 / FM-3.3 have no
   behaviour in this annotation vocabulary, invented content and
   discontinued reasoning have no detector and were never forced onto
   an adjacent id).
2. Only traces with **exactly one** covered gold mode become benchmark
   rows (single-label evaluation; multi-label golds would manufacture
   precision numbers).
3. Everything excluded is counted, never dropped silently:

```
converted 13 | excluded: 14 multi-label, 346 no covered mode,
              87 unannotated, 3 unreadable
gold distribution: FM-3.2 x6, FM-2.1 x2, FM-2.2 x2, FM-2.3 x2, FM-2.6 x1
```

## Result: accuracy 0.00, macro-F1 0.00 (rules-only)

**Every detector missed every gold.** That is the honest number, and it
comes with a structural explanation, not an excuse:

- The annotated corpus is **chat-shaped**. The gold behaviours are
  annotated over message trajectories (assistant/user turns); the rule
  detectors fingerprint *tool calls* — mutating-call names, repeated
  (tool, args) pairs, verification markers on tool steps. The
  converter maps assistant turns to tool steps only to keep the trace
  schema; no detector is designed to read prose turns as actions.
- FM-3.2 (no attempt to verify) is structurally unreachable on this
  corpus: the detector requires an unverified *mutating tool call*,
  and converted chat traces contain none by construction.
- With n=13 single-label traces the page has no statistical power
  anyway. It is published as a v1 baseline of the *pipeline*, not as a
  claim about detector quality.

## What this means

approx's rule detectors target the domain they ship for: tool-using
agents (LangGraph, AutoGen, OpenAI Agents SDK traces with real tool
calls). The reproducible quality-floor suite (tests/test_detectors.py,
tests/test_full_mast_coverage.py) pins per-mode precision/recall on
tool-shaped failure traces. Reading annotated *chat* trajectories
would need a prose-level detector family — that is future work, and
this benchmark exists precisely to measure it when it exists.

## Reproduce

```bash
git clone --depth 1 https://github.com/multi-agent-systems-failure-taxonomy/MAST.git
approximately convert-mast MAST/traces mast-bench.jsonl
approximately benchmark mast-bench.jsonl --html leaderboard.html
```
