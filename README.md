# approximately

**Approximate memory, exact accountability.**

Agents run on approximations: lossy context windows, summarized memory, sampled
traces. **approximately** is the reliability stack that makes those
approximations safe, in two halves that share one flight recorder:

- **Context runtime** — treat context as a *budgeted resource*: pins for facts
  that must never vanish, policy-driven eviction, and a **recall probe** that
  turns "did compaction eat my critical fact?" into a number.
- **Flight recorder & postmortems** — record any agent run, attribute the
  failure with the [MAST taxonomy](https://arxiv.org/abs/2503.13657) (14
  failure modes, 3 categories), replay it step-by-step, and generate pytest
  regression guards so it never happens again.

Zero required dependencies · stdlib only · Python 3.9+ · MIT.

---

## The 30-second tour

```bash
pip install approximately
approximately demo
```

A deterministic travel-booking agent fails in three classic ways. You get, on
your terminal:

```text
recorded demo trace 88e0b7d84484 (6 steps)
──────────────────────────────────────────────────────────────
  VERDICT  FM-1.3 Step Repetition
  FM-1.3 Step Repetition at step #2: The agent unnecessarily redoes steps it already completed.
──────────────────────────────────────────────────────────────
  · FM-1.3 via rule:RepeatDetector (confidence 0.80) — step #2
      - first call: #1 [tool_call] search_flights: JT-044 SFO→NRT 06-14 $870 12h40m 1 stop | KE-102 SFO→NRT 06-14 $912 1...
      - repeated call: #2 [tool_call] search_flights: JT-044 SFO→NRT 06-14 $875 12h40m 1 stop | KE-102 SFO→NRT 06-14 $918 1...
      - 2 identical calls within a 6-step window
  · FM-3.1 via rule:PrematureTerminationDetector (confidence 0.70) — step #5
      - final response: #5 [response] response: Done! Booked JT-044 SFO→NRT on 06-14, seat 12A, $870 (under your $900...
      - run marked failed (trace.success = False)
      - no goal-completion checklist was evaluated before terminating
  · FM-3.2 via rule:MissingVerificationDetector (confidence 0.70) — step #4
      - mutating call: #4 [tool_call] book_flight: BOOKED confirmation #B-2231 (unverified) (meta.mutating=true)
      - no verification step anywhere after it
      - errors from mutating calls propagate silently to the final answer
  SUGGESTED FIXES
    1. Track completed actions in an explicit working state and check it before each call.
    2. Short-circuit identical (tool, args) calls with the recorded result (Approximately replay cache).
    3. Add a stop condition to the planning loop.
──────────────────────────────────────────────────────────────

──────────────────────────────────────────────────────────────
  CONTEXT RUNTIME — what a 60-token budget would do to this run
──────────────────────────────────────────────────────────────
  context forecast for 88e0b7d84484 @ budget 60 tokens
    full context: 182 tokens | budgeted: 55 | saved: 127
    evictions: 2 | effective recall 50% (2 kept, 2 lost)
    lost facts: search_flights#1, search_flights#2
    hint: pin critical facts (runtime.pin) or raise the budget
──────────────────────────────────────────────────────────────
HTML report: /tmp/apx_readme2/88e0b7d84484.report.html
```

Open the HTML report: the verdict, the evidence chain, where your failure mode
sits in the MAST distribution, the full recorded timeline with the guilty steps
highlighted, and an editable fix list.

## Why it exists

| Fact | Source |
|---|---|
| 41.8% of agent failures are specification & design issues; 17.1% are *step repetition* alone | [MAST, arXiv:2503.13657](https://arxiv.org/abs/2503.13657) |
| Failure attribution is automatable today: an LLM judge reaches F1 0.80 vs human agreement κ 0.88 | MAST |
| Adding one verification step fixes +15.6% absolute success rate | MAST intervention study |
| Pruning + summarization beats full context: **91.6% vs 71.0% task success, 2.7× fewer tokens** | [arXiv:2606.10209](https://arxiv.org/abs/2606.10209) |
| Long-horizon GUI agents pass 85% of single tasks but only ~31% of long-horizon ones | OSWorld / OSWorld 2.0 |

The research says failures are *engineering* failures with known fixes. The
tooling to apply those fixes automatically — that's this repo.

## Quickstart

### 1. Record your agent (5 lines)

```python
from approximately import Recorder, agentstep

@agentstep
def search_flights(origin, destination): ...

with Recorder("find the cheapest SFO-NRT flight and book seat 12A") as rec:
    rec.plan("search, pick cheapest under $900, book, verify")
    search_flights("SFO", "NRT")                     # auto-recorded
    rec.tool("book_flight", {"seat": "12A"}, mutating=True, result="BOOKED #B-1")
    rec.respond("Done!", success=True)
# rec.trace is recorded; on exit it is saved to ~/.approximately/traces/
```

Works with any framework — LangGraph, OpenAI Agents SDK, CrewAI, a while loop.
If your code can call a function, it can be recorded.

### 2. Attribute the failure

```bash
approximately attribute <trace-id>          # rule detectors, offline, free
approximately attribute <trace-id> --judge  # + LLM verdict (OpenAI-compatible)
```

The rule engine detects the mechanical MAST signatures (repeated steps,
conversation resets, mutating calls with no verification, premature stops,
spec violations, derailment). The judge — any OpenAI-compatible endpoint,
including a local model — covers the semantic modes. Disagreements are shown,
never hidden.

### 3. Replay and pin it down

```python
from approximately import replay

diff = replay(trace, executor=my_executor)
print(diff.summary())   # reproduced / consistent / diverged, per-step diffs
```

`reproduced` = the exact failure fires again at the exact step. Now change one
thing, replay again, and watch the verdict flip.

### 4. Generate regression guards

```bash
approximately test <trace-id> -o tests/test_regress_booking.py
pytest tests/test_regress_booking.py
```

The generated file embeds the trace (base64, self-contained) and emits pytest
guards per failure mode: *no repeated (tool, args) calls*, *every mutating call
is verified*, *runs never end silently on an error* — plus a replay-consistency
guard for CI.

### 5. Budget your context before production does

```python
from approximately import ContextRuntime

rt = ContextRuntime(budget_tokens=2000, task="book seat 12A under $900")
rt.pin("budget-cap", "$900 hard cap")        # never evicted
rt.add_tool_result("search#1", huge_result)
probe = rt.recall_probe({"cheapest": "JT-044 $870"})
print(probe.summary())                        # effective recall 100% (1 kept, 0 lost)
```

And forecast any budget against a recorded run *before* deploying it:

```bash
approximately context <trace-id> --budget 800
```

## The MAST taxonomy inside

`approximately taxonomy` prints all 14 failure modes with their published
distribution:

```text
[FC1] Specification & System Design Issues (41.77% of failures)
  FM-1.3  Step Repetition              17.14% of traces
  FM-1.5  Unaware of Termination        9.82%
  ...
[FC2] Inter-Agent Misalignment (36.94%)
[FC3] Task Verification (21.30%)
```

## Design principles

1. **Zero dependencies.** The core never imports anything outside the standard
   library. Attribution works offline, deterministically, and for free.
2. **Evidence or it didn't happen.** Every detection carries a human-readable
   evidence chain pointing at step indices. No magic numbers.
3. **Never hard-fail attribution.** No API key, no network, no problem — rules
   degrade gracefully; the judge is a bonus, not a dependency.
4. **Failures are engineering, not vibes.** Every verdict ships with fixes
   backed by published intervention numbers.

## Roadmap

- **v0.2** — LangGraph / OpenAI Agents SDK / CrewAI adapters; judge distillation
  to small local models; attribution benchmark on MAST-Data.
- **v0.3** — cross-trace failure clustering ("your team's recidivist modes");
  context-runtime integration with the regression guards (budget regressions);
  token-cost vs success-rate curves from arXiv:2606.10209 as a first-class report.

See [docs/PLAN.md](docs/PLAN.md) for the full design & launch plan.

## Contributing

Issues and PRs welcome. Good first issues: framework adapters, detectors for
the remaining MAST modes (FM-2.2, FM-2.4–2.6, FM-3.3), a tokenizer-optional
token counter.

## Citation

If Approximately helps your research:

```bibtex
@software{approximately2026,
  title  = {approximately: approximate memory, exact accountability for AI agents},
  year   = {2026},
  url    = {https://github.com/B1ueMu3ic4m/approximately}
}
```

Failure taxonomy by Cemri et al., *Why Do Multi-Agent LLM Systems Fail?*
([arXiv:2503.13657](https://arxiv.org/abs/2503.13657)).

## License

[MIT](LICENSE)
