# Tutorial: from a failing agent run to a CI-enforced fix

Ten minutes, zero dependencies. Every command below is exercised by
the README walkthrough tests (`tests/test_v46_readme_walkthrough.py`),
so this tutorial cannot silently drift from the tool.

## 0. Install and tour

```bash
pip install approximately
approximately demo                 # scripted agent failing in classic ways
approximately demo --scenario loop            # multi-agent cycle (FM-1.3)
approximately demo --scenario verification    # unchecked claim (FM-3.2)
```

Each demo records a trace into `~/.approximately/traces`, attributes it,
and writes an HTML postmortem next to the JSON.

## 1. Record your own agent

Five lines around any Python callable:

```python
from approximately import Recorder

with Recorder("book the cheapest SFO-NRT flight") as rec:
    flights = search_flights("SFO", "NRT")            # your code, recorded
    rec.tool("book_flight", {"seat": "12A"}, result="BOOKED #1",
             mutating=True)
    rec.respond("Booked!", success=True)
```

The trace is saved on exit. For LangChain/LangGraph, OpenAI Agents SDK,
CrewAI, LlamaIndex, or AutoGen, drop in a contrib adapter instead —
see `docs/ARCHITECTURE.md`.

## 2. Attribute the failure

```bash
approximately attribute <trace-id>
```

You get the primary MAST failure mode, the step that broke, the evidence
chain, and suggested fixes. Add `--explain` to see the fusion arithmetic
(prior log-odds + per-detection evidence weights), or `--judge` to add an
optional LLM verdict on top of the rules.

## 3. Prove the fix with a bisect

Fixed the code? Compare the failed run against its last success — the
earliest *material* divergence is where it went wrong:

```bash
approximately bisect <failed-id> <success-id>       # add --json for CI
```

Mutations whose results are near-identical (timestamp noise) are floored
out; the report ranks the worst divergences so you fix the cause, not a
symptom.

## 4. Guard it forever

```bash
approximately test <failed-id> --budget 800
```

writes a self-contained pytest file (the trace rides along as base64) —
commit it and the failure can never silently return. The store's health
is also gateable:

```bash
approximately doctor ~/.approximately/traces --fix     # exit 1 = problem
approximately verify --all                             # evidence intact
```

## 5. Watch the fleet

Multiple agents or projects? Point the watch loop at their stores and let
the trend gate decide:

```bash
approximately fleet storeA storeB --watch 300 --digest-dir digests &
approximately fleet --trend --digest-dir digests --fail-on-worsening
```

`--trend` prints per-day failure rates, a sparkline, and a Theil–Sen
verdict; `--fail-on-worsening` turns "the agents are getting worse" into
a red build.

## 6. Pin attribution quality itself

If you keep labeled traces, run the same gates upstream does:

```bash
python scripts/bench_gate.py          # gold-corpus floors
python scripts/bench_gate.py --synth  # 180-record synthetic canary
python scripts/perf_gate.py           # attribution stays fast
```

## Where to go next

- Capabilities overview: [README](../README.md#the-capabilities-at-a-glance)
- Module map: [docs/ARCHITECTURE.md](ARCHITECTURE.md)
- Threat model: [docs/SECURITY.md](SECURITY.md)
- Roadmap: [docs/PLAN.md](PLAN.md)
