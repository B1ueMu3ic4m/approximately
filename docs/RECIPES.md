# Recipes

Task-shaped walkthroughs. Every command shown is part of the CLI or
the package API; snippets are kept in sync with the tests and demos
that run in CI. The ten-minute basics live in
[TUTORIAL.md](TUTORIAL.md); this page is the cookbook.

## 1. Instrument a plain-Python agent (5 lines)

```python
from approximately import Recorder

with Recorder("fix the flaky test", store=TraceStore("traces")) as rec:
    ...
    rec.tool("bash", {"cmd": "pytest -k flaky"}, result="1 failed")
    rec.respond("patched the fixture", success=True)
```

Every step lands in a tamper-evident store. `store=TraceStore()` honors
`APPROXIMATELY_HOME`; without it traces go to the default home.

## 2. Name your agents, get a scoreboard

Multi-agent run? Give the recorder an agent identity (or override per
call) and `stats --by-agent` rolls up who did what:

```python
with Recorder("research + brief", store=store, agent="orchestrator") as rec:
    rec.plan("split work", agent="orchestrator")
    rec.tool("web_search", {"q": "token costs"}, result="3 hits",
             agent="researcher")
    rec.message("researcher", "writer", "findings attached")
    rec.tool("write_draft", {"topic": "token costs"}, result="v1",
             agent="writer")
```

```console
$ approximately stats --by-agent --store traces
  agent                traces  steps  tools  tokens errors failed   rate
  researcher                1      3      2      60      0      1   100%
  ...
```

`rate` is the share of traces an agent *touched* that failed —
participation, not proven causation. Steps without identity surface
under `unattributed`, so instrumentation gaps stay visible.

## 3. Attribute a failure and act on it

```console
$ approximately attribute traces/<id> --explain
$ approximately explain FM-1.3        # definition, share, detectors, fixes
$ approximately bisect <failed-id> <success-id> --store traces
```

`--explain` shows the fusion arithmetic; `explain <mode>` answers
"what does this mean for my agent and what do I change"; `bisect`
finds the first *material* divergence between a failing and a healthy
run (timestamp noise floored).

## 4. Turn failed runs into CI guards

```console
$ approximately test traces/<id>          # writes a pytest regression file
$ approximately test traces/<id> --budget 2000   # also guard context budget
```

The generated tests live in your repo and fail when the same failure
mode reappears.

## 5. Gate attribution quality in your own CI

You own a labeled dataset (JSONL: one trace + gold labels per line,
what `export-dataset` writes). Floors follow
[bench-floors.json](bench-floors.json). Then either run the command:

```console
$ approximately bench-gate eval/attribution.jsonl --floors eval/floors.json
```

…or use the shipped GitHub Action:

```yaml
- uses: B1ueMu3ic4m/approximately@v0
  with:
    dataset: eval/attribution.jsonl
    floors: eval/floors.json
```

A detector or model change that silently degrades precision/recall
now fails the build.

## 6. Nightly integrity cron

```console
$ approximately verify --all --store traces --strict --quiet \
  || curl -H content-type:application/json -d '{"text":"integrity gate FAILED"}' $SLACK
$ approximately doctor traces --fix
```

Default `verify --all` passes unsigned records with a note; `--strict`
enforces "every record must carry verifiable evidence" as the exit
code. `doctor --fix` removes stale locks and temp files.

## 7. Fleet dashboards and a worsening trend gate

```console
$ approximately fleet ~/agents/*/traces --fleet-html fleet.html
$ approximately fleet --watch 3600 --digest-dir digests
$ approximately fleet --trend --digest-dir digests --fail-on-worsening
```

The watch loop appends daily JSONL snapshots; the trend gate computes
a Theil–Sen verdict over the history and fails CI when the fleet is
getting worse. One agent's trajectory over the same history:

```console
$ approximately fleet --trend --agent researcher --digest-dir digests
```

(A day shows an agent while it is among that store's top-3 busiest
named agents in the snapshot; a zero row means *not observed*.)

## 8. Query failures without loading anything

```console
$ approximately query "success == false and mode == FM-2.1" --store traces
$ approximately query "model contains 'gpt' and steps > 40" --stats
$ approximately query "agents contains 'researcher'" --store traces
```

The DSL is a recursive-descent parser with depth/length caps — no
`eval`, no injection surface.

## 9. Talk to it over MCP

Claude Desktop / Zed / any MCP client config:

```json
{"mcpServers": {"approximately":
    {"command": "approximately", "args": ["mcp", "--store", "/path/traces"]}}}
```

The inventory spans store access (list_traces, query, stats,
trend, survey), attribution and explanation (attribute, explain,
cluster, bench_gate), verification (verify — the full verdict
ladder), comparison (bisect, similar, diff), prediction and
analysis (predict, counterfactual, drift, context, curve,
anomalies), fleet health (doctor, scoreboard, metrics), triage
(annotate — write with a note, read without) and self-guarding
(regression_test) — the whole toolkit, stdio JSON-RPC, zero deps.
`tools/list` is the authoritative, always-current list.

## 10. Local-model judge (sensitive runs)

```console
$ approximately attribute traces/<id> --judge --judge-model qwen2.5:7b
$ approximately distill -o training.jsonl              # export your own judge data
```

Per-serving-stack recipes (Ollama, llama.cpp, vLLM, TGI, OpenAI
fine-tunes) live in [DISTILLATION.md](DISTILLATION.md). The judge
endpoint sees your trace content — use a local model for sensitive
runs (see [SECURITY.md](SECURITY.md)).

## 11. Which run is this one like? (alignment neighbours)

A run just failed. Before reading the whole report, ask which past
runs it structurally resembles — known failure shapes surface
immediately:

```bash
approximately similar <trace-id> --top 5
# or over MCP: tools/call similar {trace, store, top}
```

Scores are structure-aware sequence alignment over steps (in [0, 1]),
best first. A 0.9 neighbour that failed last Tuesday is the fastest
diagnosis you will ever get.

## 12. Is the fleet drifting? (PSI between windows)

Split the store's history into an old baseline and a recent window
and measure how far the action histogram has moved:

```bash
approximately drift --baseline-ratio 0.6
# or over MCP: tools/call drift {store, baseline_ratio}
```

The Population Stability Index comes with a verdict and the biggest
shifted actions — "deploy went from 2% to 18% of actions" is a
behaviour change, not noise. Pair it with `fleet --trend
--fail-on-worsening` in CI for a drift tripwire.

## 13. Watch the fleet and page only on signal

Continuous monitoring with digest history, and a webhook that fires
only when something is actually wrong — a worsening trend or a
failure rate at/above the line:

```bash
approximately fleet storeA storeB \
  --watch 300 --digest-dir digests \
  --webhook https://hooks.example/teams/agents \
  --alert-worse-than 0.3
```

Snapshots land in `digests/` every cycle no matter what (the trend
history is never gated); the webhook POSTs the HMAC-signed summary
only on signal. Pair with `--iterations` for cron-driven batches:

```bash
approximately fleet storeA --watch 300 --digest-dir digests \
  --webhook $URL --alert-worse-than 0.3 --iterations 288
```

288 iterations x 5 minutes = a full day, then the cron starts a new
watch. A torn digest line, a dead endpoint, or a crashed writer must
never stop the loop — the toolkit treats the watch itself as the
thing that has to survive the night.
