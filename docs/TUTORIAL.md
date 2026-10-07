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
(prior log-odds + per-detection evidence weights), `--top 2` to see the
runner-up hypotheses the detectors also fired for, or `--judge` to add an
optional LLM verdict on top of the rules. When the verdict names a mode
you have never heard of:

```bash
approximately explain FM-1.3
```

answers "what does this mean for my agent" — definition, published
share, the detectors watching for it, and the engineering fixes.

## 3. Name your agents

Multi-agent runs get a per-agent scoreboard when the recorder knows who
acted:

```python
Recorder("task", store=store, agent="orchestrator")
rec.tool("web_search", {...}, agent="researcher")   # per-call override
rec.message("researcher", "writer", "findings")     # sender stamped
```

```bash
approximately stats --by-agent --store storeA
approximately cluster --store storeA --by-agent    # recidivist agents
approximately fleet --trend --agent researcher --digest-dir digests
```

Steps without identity surface under `unattributed` so gaps stay
visible; agent identity is hash-chain covered, so rewriting it on
saved traces is tamper-evident.

## 4. Prove the fix with a bisect

Fixed the code? Compare the failed run against its last success — the
earliest *material* divergence is where it went wrong:

```bash
approximately bisect <failed-id> <success-id>       # add --json for CI
```

Mutations whose results are near-identical (timestamp noise) are floored
out; the report ranks the worst divergences so you fix the cause, not a
symptom.

## 5. Guard it forever

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

## 6. Triage and check the pulse

Attach the human verdict to the machine one (append-only sidecar —
the evidence chain stays untouched), then read the store's pulse in
one command:

```bash
approximately annotate <id> "infra timeout" --author oncall --verdict confirmed
approximately status
```

`status` prints totals, top failure modes, triage tallies, and the
last failing trace with its chain verdict. Point `--digest-dir` at
your watch history to fold the fleet trend in, or `--json` for a
dashboard.

## 7. Watch the fleet

Multiple agents or projects? Point the watch loop at their stores and let
the trend gate decide:

```bash
approximately fleet storeA storeB --watch 300 --digest-dir digests &
approximately fleet --trend --digest-dir digests --fail-on-worsening
```

`--trend` prints per-day failure rates, a sparkline, and a Theil–Sen
verdict; `--fail-on-worsening` turns "the agents are getting worse" into
a red build. The same surfaces exist over MCP (see
[RECIPES.md](RECIPES.md) §9), including `scoreboard.min_failed` for
repeat offenders and `drift` for behaviour shifts.

## 8. Pin attribution quality itself

If you keep labeled traces, run the same gates upstream does:

```bash
approximately bench-gate my-data.jsonl --floors my-floors.json
python scripts/bench_gate.py          # gold-corpus floors
python scripts/bench_gate.py --synth  # 180-record synthetic canary
python scripts/perf_gate.py           # attribution stays fast
```

In another repo's workflow, the shipped action does the same gate:

```yaml
- uses: B1ueMu3ic4m/approximately@v0
  with: { dataset: eval/attribution.jsonl, floors: eval/floors.json }
```

## 9. Or start from the logs you already have

No instrumentation? No problem — a JSONL dump of past runs becomes a
tamper-evident store in one command, and the whole tutorial above
works on it exactly as on freshly recorded runs.

```bash
approximately import logs/ --store ~/agents/store   # a directory, glob, or -
approximately report ~/agents/store --all           # postmortems for history
approximately anomalies ~/agents/store --all        # was anything quietly slow?
```

Details and the round-trip (export back out, ids restored) live in
[RECIPES 14](RECIPES.md).

## 10. The OpenTelemetry loop

Your agent's failures can live next to the rest of the stack's
telemetry, and the loop goes both ways:

```bash
# out: Jaeger/Tempo/Honeycomb ingest agent runs as spans
approximately export --store ~/agents/store runs.otlp.json --format otel

# in: a backend export (or any OTLP document) becomes a store
approximately import --store ~/agents/store runs.otlp.json   # sniffed
```

Deterministic ids make the loop idempotent, and export → import →
export closes byte-for-byte — the same run always produces the same
document.  Or let it happen on its own: `approximately spool --dir
~/spool` watches a directory (recipe 18), and `doctor --spool`
tells you when a file needs a human.

## Where to go next

- Capabilities overview: [README](../README.md#the-capabilities-at-a-glance)
- Module map: [docs/ARCHITECTURE.md](ARCHITECTURE.md)
- Threat model: [docs/SECURITY.md](SECURITY.md)
- Roadmap: [docs/PLAN.md](PLAN.md)


## 11. From regression to evidence: closing the loop

The last chapter of the tour is the one your future self thanks
you for: when a run fails in production, the questions arrive
before the context does.  Three commands answer them in order.

```bash
# what happened: the postmortem, offline and free
approximately attribute <trace-id>

# can it be trusted: is this record the run that happened?
approximately doctor --store ~/.approximately/traces --deep
approximately evidence <trace-id> case.zip
```

`case.zip` is the hand-off: the record with its integrity chain,
the HTML postmortem, the on-call notes, and a sha256 manifest a
reviewer can recompute with `unzip` and `sha256sum` — no store,
no tool, no trust required.  Keyed chains verify with
`--key-file`.

And when the same failure starts repeating across runs, stop
reading reports and start failing builds:

```bash
approximately init                    # wire the gate once
approximately ci --max-failure-rate 0.2   # exit 1 in CI
```

The recorder wrote the evidence; the gate makes someone read it;
the pack proves it was never rewritten in between.

## 12. Stop the burn: live budgets

The agent has been looping for a while now.  Each retry re-reads the
whole inventory into context; the token counter climbs; nobody is
watching.  The gate will catch it — after the run, when the money is
gone.  A Budget catches it during.

```python
from approximately.budget import Budget
from approximately.recorder import Recorder

budget = Budget(tokens=50_000, on_exceed="raise")
with Recorder("find and book the flight", model="gpt-4o",
              store=store, budget=budget) as rec:
    for attempt in attempts:          # your agent loop
        rec.tool("search_flights", {...}, tokens=cost_of(attempt))
```

When the run crosses 50,000 tokens the loop dies with
`BudgetExceededError` — and the trace that lands in the store is not
a mystery: the offending step is on the record, the run is marked
failed, and `meta["budget"]` carries the meters and the verdict,
covered by the integrity signature like everything else.

Open the report and the receipt is right there: the Live budget
card shows tokens against ceiling, estimated spend against ceiling,
and a red BREACHED badge — the postmortem answers "why did this run
stop early?" without a diff.

Then let the machinery carry it forward: `ci --max-budget-breaches 0`
keeps burned runs out of your pipeline, `fleet
--alert-budget-breaches 1` pages when a store starts burning, and
`clean --keep-breached` makes sure housekeeping never deletes the
evidence before the postmortem reads it.

## 13. The on-call loop: the operations night

Everything you have built — a store with signed traces, named
agents, a CI gate, live budgets, a digest — now runs as a loop:

```bash
approximately prices set gpt-4o 2.5      # rates live with the store
approximately tail                       # arrivals, failures flagged
approximately triage --since-days 1      # the morning queue
approximately grade                      # which agent is drifting
approximately handoff <trace> --redact   # the one-page brief
approximately snapshot night.zip         # the night leaves safely
```

The nightly audit composes the same loop with a single exit code
(and `--week-compare` answers "what just changed" next to the
forecast's "where is this heading"):

```bash
approximately audit --store .agents-store --digest-dir d \
  --fix --grade-floor F --triage-top 5 --week-compare
```

If your agents live inside an MCP client, the whole surface is
answerable without a shell: 49 tools, and the operations state
(`grades`, `triage`, `prices`) is browsable as resources.

Version numbers follow [VERSIONING.md](VERSIONING.md): majors are
capability milestones with a real contract change, minors are one
feature batch each.
