# approximately

[![CI](https://github.com/B1ueMu3ic4m/approximately/actions/workflows/ci.yml/badge.svg)](https://github.com/B1ueMu3ic4m/approximately/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/approximately)](https://pypi.org/project/approximately/)
[![Python](https://img.shields.io/badge/python-3.9%2B-blue)](https://pypi.org/project/approximately/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

**Approximate memory, exact accountability.**

<p align="center">
<b>Free & open source · Zero dependencies · MIT · Python 3.9+ · pip install approximately</b>
</p>

---

## What is approximately?

**approximately is a dashcam and crash-investigation report for your AI agents.**

AI agents plan on their own, call tools on their own, and execute tasks that span dozens of steps — and you can barely see what they actually did. When one fails, all you know is *"it failed"*: not which step broke, not what kind of failure it was, and not whether it will happen again tomorrow.

approximately records every step an agent takes. When a run fails, it tells you **which step broke and which of the 14 scientifically-classified failure modes it belongs to**, plus how to fix it. It replays the run to verify the fix actually works, and turns the failure into an automated test so it never ships again. It also answers the question every team eventually asks: **how big should the agent's context window actually be?** Too big wastes money; too small and the agent starts "forgetting" critical facts — approximately gives you the numbers.

## What pain does it kill?

| What you're stuck with | What approximately gives you |
|---|---|
| "The agent failed and the log is 3,000 lines — I don't know which step broke" | Automatic attribution: **the exact step and failure mode** (e.g. "step #2: repeated an already-completed action" — the single most common failure in research, 17% of all traces) |
| "I fixed it, but it broke the same way next week" | Failed runs become **regression tests automatically**; the second occurrence fails CI |
| "Re-running costs money — I don't want to guess" | **Step-level replay**: verify the fix without re-running the whole task |
| "How big should the context window be? Will compression lose critical facts?" | **Context budgeting**: see exactly where a shrinking budget starts making the agent forget — and guard it in CI |
| "Of our last 100 failures, what should we fix first?" | **Recidivist clustering**: groups failures across runs and surfaces the systematic patterns |
| "Agent logs are too long for humans to review" | Every verdict carries an evidence chain pointing at exact steps — review only what matters |
| "Prove the evidence wasn't edited after the incident" | **Tamper-evident hash chains**: `approximately verify` detects and localizes any post-hoc edit; HMAC keys defend against deliberate forgery |

## Why trust the numbers?

The failure taxonomy inside approximately comes straight from 2025–2026 research, not vibes:

- Multi-agent failures classify into **14 failure modes across 3 categories** ([MAST, arXiv:2503.13657](https://arxiv.org/abs/2503.13657); 1,600+ human-annotated traces, inter-annotator agreement κ = 0.88)
- **41.8% of failures are specification & design issues** (organizational, not model stupidity) and **21.3% are missing verification** — both fixable with engineering
- The same research showed adding a single verification step improves success by **+15.6% absolute** (approximately's fix suggestions cite these numbers)
- "Curating context beats stuffing it" is measured too: pruning + summarization took task success from **71.0% to 91.6%** while using **2.7× fewer tokens** ([arXiv:2606.10209](https://arxiv.org/abs/2606.10209))

## Who is it for?

- **Agent developers** — your agent is in production; you need "investigable when it breaks, prevented afterward"
- **Tech leads** — you want data on what to fix first, not gut feeling
- **AI application startups** — when a customer asks "why was this result wrong?", you can produce the evidence chain
- **Researchers** — a MAST-mode classifier, a benchmark harness, and distillation exporters out of the box

## How it works, step by step

1. **Record** — wrap your agent in a flight recorder; every tool call, thought, and result is archived (one-file adapters for LangChain/LangGraph, OpenAI Agents SDK, and CrewAI)
2. **Attribute** — on failure, a built-in rule engine plus an optional LLM judge deliver the verdict: mode, step, evidence chain, suggested fixes
3. **Replay** — re-execute the recorded steps and diff every outcome to prove the fix works
4. **Prevent** — one command turns the failure into a pytest regression guard that lives in CI

<details>
<summary><b>🔧 Developer quickstart (2 commands + 5 lines)</b></summary>

```bash
pip install approximately
approximately demo        # 30-second tour: a scripted agent that fails in classic ways
approximately demo --scenario loop             # multi-agent cycle: only the cycle detector catches it
approximately demo --scenario verification    # unchecked claim: FM-3.2 end to end
approximately demo --scenario multi-agent   # researcher/writer crew: information withholding
```

```python
from approximately import Recorder, agentstep

@agentstep
def search_flights(origin, destination): ...   # decorated calls record themselves

with Recorder("book the cheapest SFO-NRT flight") as rec:
    search_flights("SFO", "NRT")               # auto-recorded
    rec.tool("book_flight", {"seat": "12A"}, mutating=True, result="BOOKED #1")
    rec.respond("Booked!", success=True)
# the trace is saved on exit; one command produces the postmortem
```

```bash
approximately attribute <trace-id>            # automatic attribution (offline, free)
approximately attribute <trace-id> --judge    # add the LLM judge (optional)
approximately test <trace-id> --budget 800    # regression guards + budget guard
```

</details>

<details>
<summary><b>📺 Real terminal output (what the demo looks like)</b></summary>

```text
recorded demo trace 4deba35fcf37 (6 steps)
──────────────────────────────────────────────────────────────
  VERDICT  FM-1.3 Step Repetition
  FM-1.3 Step Repetition at step #2: The agent unnecessarily redoes steps it already completed.
──────────────────────────────────────────────────────────────
  · FM-1.3 via rule:RepeatDetector (confidence 0.80) — step #2
      - first call: #1 [tool_call] search_flights: JT-044 SFO→NRT ...
      - repeated call: #2 [tool_call] search_flights: JT-044 SFO→NRT ...
      - 2 identical calls within a 6-step window
  · FM-3.1 via rule:PrematureTerminationDetector (confidence 0.70) — step #5
  · FM-3.2 via rule:MissingVerificationDetector (confidence 0.70) — step #4
  SUGGESTED FIXES
    1. Track completed actions in an explicit working state ...
──────────────────────────────────────────────────────────────
  CONTEXT RUNTIME — what a 60-token budget would do to this run
──────────────────────────────────────────────────────────────
  context forecast for 4deba35fcf37 @ budget 60 tokens
    full context: 182 tokens | budgeted: 55 | saved: 127
    evictions: 2 | effective recall 50% (2 kept, 2 lost)
    lost facts: search_flights#1, search_flights#2
    hint: pin critical facts (runtime.pin) or raise the budget
──────────────────────────────────────────────────────────────
HTML report: ~/.approximately/traces/4deba35fcf37.report.html
```

The same trace also renders a visual HTML postmortem: the verdict, the evidence chain, where your failure mode sits in the research distribution, the full timeline with guilty steps highlighted, and the fix list.

</details>

---

## The capabilities at a glance

| Capability | In one sentence | Command / API |
|---|---|---|
| 📼 Flight recorder | Zero-dependency recording of every agent step — including inter-agent messages — any framework | `Recorder` / adapters |
| 🔍 Failure attribution | **All 14 MAST modes** covered by rule detectors; Bayesian fusion ranks verdicts by MAST base rates × evidence likelihood | `approximately attribute` |
| 🛡️ Tamper-evident evidence | Per-step hash chain + optional HMAC; `verify` detects edits, the ledger catches **rolled-back** traces, and `verify --all` gates a whole store in CI | `approximately verify [--all]` |
| 🧩 Fleet merge | Union another team's store, refusing broken evidence; id conflicts via skip/replace/rename | `approximately merge <source>` |
| 🗺️ Fleet dashboard | All your stores on one page: failure rates, trend sparklines, top modes, broken ledgers | `approximately fleet <dir>... --fleet-html` |
| 🔔 Fleet alerts | HMAC-signed JSON webhooks when a store's trend turns worse — receivers authenticate alerts like evidence | `approximately fleet --webhook URL` |
| ⏱️ Latency anomalies | Median/MAD modified z-score — flags slow *and* fast outlier steps without being fooled by tails | `approximately anomalies <trace>` |
| 🔁 Step-level replay | Verify fixes without re-running the task; A/B compare original vs patched executors | `approximately replay --patched` |
| 🧪 Regression guards | Failed runs become pytest tests that live in CI | `approximately test` |
| 📉 Context budgeting | "Where does a shrinking budget start losing facts?" — guarded in CI | `approximately context` / `test --budget` |
| 🎯 Budget optimizer | Binary-searches the **smallest context window that keeps recall ≥ target** | `approximately optimize` |
| 🔎 Recidivist clustering | Cross-run statistics of your systematic failure modes | `approximately cluster` |
| 📈 Failure-rate trends | "Is the agent getting better or worse?" — sparkline + robust Theil–Sen verdict in every batch report | `approximately report --all` / `stats --trend` |
| 🚀 Project scaffold | An instrumented agent project with guards, runnable in seconds | `approximately new myagent` |
| 🔮 Failure precursor | Early warning mined from your own history: "runs like this fail Z% of the time" | `approximately predict` |
| 🧬 Trajectory alignment | Needleman-Wunsch over action sequences — find runs with the same *shape* | `approximately similar` |
| 📮 SARIF export | Attribution results as GitHub code-scanning alerts | `approximately attribute --sarif` |
| 🕵️ Tool-poisoning scanner | Static analysis of MCP tool descriptions (homoglyphs, bidi, injection) | `approximately scan-tool` |
| 🧪 Conformal attribution | Prediction **sets** with a distribution-free 90% coverage guarantee — ambiguity widens the set honestly | `calibrate` + `attribute` |
| 🌡️ Drift detection | PSI over action distributions — catches prompt/model changes before failures spike | `approximately drift` |
| ⚡ Counterfactual RCA | do(step=∅) experiments separating root causes from symptoms | `approximately counterfactual` |
| 📡 Streaming monitor | Live failure-risk over in-flight runs — precursor + repetition + verification-debt signals with hysteresis | `StreamingMonitor.observe()` |
| 🔧 Repair search | Smallest validated intervention set that clears attribution (or honest "unrepairable") | `approximately repair` |
| 📊 Prometheus export | Agent reliability on your Grafana dashboards, with per-mode counters | `approximately metrics --prometheus` |
| 🪮 First-fault bisect | "Where did this run leave the good path?" — earliest *material* divergence on the edit script, timestamp noise floored | `approximately bisect FAILED SUCCESS` |
| 🩺 Store doctor | Parseable records, ledger tamper, stale locks, digest gaps — self-healing with `--fix` | `approximately doctor STORE [--fix]` |
| 📡 Fleet trend gate | Day-level digest analytics with a Theil–Sen verdict that fails CI when the fleet worsens | `approximately fleet --trend --fail-on-worsening` |
| 🔎 Query DSL + stats | Select traces with an expression — or aggregate the selection: counts, failure rate, mode totals, means | `approximately query "..." [--stats]` |
| 📖 Mode explainer | "What does FM-1.3 mean *for my agent*?" — definition, published share, the detectors watching it, engineering fixes | `approximately explain FM-1.3` |
| 👥 Agent scoreboard | Who did what in a multi-agent run: steps, tokens, errors, and the failure rate of traces each agent touched | `Recorder(agent="researcher")` + `approximately stats --by-agent` |
| 🔌 MCP server | The whole toolkit as a Model Context Protocol stdio server (24 tools and counting — `tools/list` is authoritative) — query failures and agent scoreboards from any MCP client | `approximately mcp` |
| 🧪 Attribution quality gates | Gold-corpus + large-n synthetic floors run in CI — a detector refactor that degrades P/R fails the build | `python scripts/bench_gate.py [--synth]` |
| 🚦 Gate as a GitHub Action | The same attribution gate as a drop-in action for your own repo's workflow | `uses: B1ueMu3ic4m/approximately@v0` |

**See it before you trust it** — real rendered artifacts, generated by the tool itself: [postmortem report](docs/artifacts/report.html) · [batch index with failure-rate trend](docs/artifacts/index.html) · [budget-vs-recall curve](docs/artifacts/curve.html) · [fleet dashboard](docs/artifacts/fleet.html) · [MAST-Data leaderboard](docs/artifacts/leaderboard.html) · [multi-label leaderboard](docs/leaderboard-multi.html) (regenerate with `python3 scripts/make_docs_artifacts.py`).

Advanced: **local small-model judge** (`distill` exports training data; per-serving-stack recipes in [docs/DISTILLATION.md](docs/DISTILLATION.md) — Ollama, llama.cpp, vLLM, TGI, OpenAI fine-tunes), **attribution benchmark** (`benchmark`, per-mode precision/recall/F1, `--html` renders a shareable leaderboard page), **cost-vs-recall curve reports** (`curve`), **threat model** ([docs/SECURITY.md](docs/SECURITY.md)).

## Design principles

1. **Zero dependencies** — the core uses only the Python standard library; attribution works offline, deterministically, and for free
2. **Evidence or it didn't happen** — every verdict carries a readable evidence chain pointing at exact steps, and every trace carries a **tamper-evident hash chain**: `approximately verify` proves the evidence wasn't edited after the fact
3. **Never make it worse** — no API key, no network? Attribution degrades gracefully; your program never crashes because of us
4. **Failures are engineering, not vibes** — every fix suggestion is backed by published intervention numbers

## FAQ

**Q: Does it work with my framework?**
Yes. The core recording API is framework-agnostic — if your code can call a function, it can be recorded. Official adapters cover LangChain / LangGraph (callback handler), OpenAI Agents SDK (tracing processor), CrewAI (event bus), AutoGen v0.4+ (event-log handler plus a transparent model-client proxy), LlamaIndex (callback-handler seam: LLM, function-call, retrieval and exception events), Pydantic AI (post-hoc message transcription), and Google ADK (post-hoc event transcription).

**Q: Does the LLM judge require internet? Does it cost money?**
No and no. The rule engine covers most mechanical failure modes offline and free (repeated steps, missing verification, premature termination…). The judge is an optional enhancement that speaks any OpenAI-compatible endpoint — including local Ollama/llama.cpp — and you can distill it down to a local small model with `distill`.

**Q: Will recording slow my agent down or leak data?**
Recording is a local JSON write taking microseconds. Everything lives under `~/.approximately/` on your machine — no telemetry, no uploads, nothing.

**Q: How do I know the evidence wasn't edited after an incident?**
Every save stamps a per-step SHA-256 hash chain into the trace. `approximately verify <trace-id>` recomputes it: any edit to any step (results, outcomes, even metadata) breaks the chain and is localized to the first altered step. For hostile environments, set a signing key (`APPROXIMATELY_SIGNING_KEY`) and the chain becomes an HMAC — an attacker with write access can no longer forge it. See [docs/SECURITY.md](docs/SECURITY.md).

**Q: Does it handle multi-agent runs?**
Yes. `Recorder.message(from, to, text)` records inter-agent messages as first-class steps, and dedicated detectors catch information withholding (a result flagged `share_with` that never reached its audience) and ignored peer input (a `requires_ack` message the recipient never acted on).

**Q: What is "context budgeting" exactly?**
An agent's working memory (context window) is finite and expensive. Stuffing it costs money and degrades recall (research shows mid-window recall collapses); shrinking it silently loses facts. approximately manages context as a budgeted resource: facts you can pin (never evicted), policy-driven eviction, and an "effective recall probe" that measures how much the agent still remembers — deployable as a CI guard so nobody quietly shrinks the window.

---

## Roadmap

- ✅ **v0.1** — flight recorder + MAST attribution + replay + regression guards + context runtime
- ✅ **v0.2** — framework adapters (LangChain/LangGraph, OpenAI Agents SDK, CrewAI) · judge distillation · attribution benchmark
- ✅ **v0.3** — cross-trace recidivist clustering · budget regression guards · cost-vs-recall curves · project scaffold · stats trends
- ✅ **v0.3.2** — Bayesian evidence fusion (MAST priors × evidence likelihood) · budget optimizer (binary-search) · tamper-evident evidence chains + `verify` · HMAC signing · security threat model
- ✅ **v0.4** — trajectory alignment (Needleman-Wunsch) · failure-precursor prediction (n-gram early warning) · SARIF export · MCP tool-poisoning scanner · HMAC key rotation
- ✅ **v0.5** — conformal attribution (coverage-guaranteed prediction sets) · NLL temperature calibration · counterfactual root-cause analysis · PSI behavior-drift detection
- ✅ **v0.6** — structural trace diff (NW traceback: failed-vs-success edit scripts) · minimal-repair search (validated prescriptions) · Prometheus export
- ✅ **v0.7** — streaming reliability monitor (live risk with hysteresis) · concurrent-safe store (atomic writes + per-id locks) · concurrency threat model
- ✅ **v0.8** — AutoGen adapter (event log + model-client proxy) · failure-rate trend with Theil–Sen verdict in HTML reports · full complexity audit (all C-rank blocks refactored below a strict bar) · security fuzzing of the new surfaces
- ✅ **v0.9** — LlamaIndex adapter (callback-handler seam) · HMAC key-ID + rotation counter with the honest `wrong-key` verdict (no more false TAMPERED after key rotation)
- ✅ **v0.10** — LlamaIndex Dispatcher seam (structured spans) · `benchmark --html` attribution leaderboard · per-serving-stack distillation recipes
- ✅ **v0.11** — evidence ledger (rollback detection: an older *validly-signed* snapshot no longer passes) · cross-store fleet merge with evidence refusal
- ✅ **v0.12** — fleet dashboard (multi-store aggregation) · MAD latency anomalies in reports and CI · fixed before-position `--store`
- ✅ **v0.13** — fleet trend alerts (`--fail-on-worsening` CI gate) · MAST-Data annotation pipeline + first real-data benchmark published ([docs/LEADERBOARD.md](docs/LEADERBOARD.md))
- ✅ **v0.14** — prose detector family for chat-shaped trajectories (5 detectors, exclusive gating) · MAST-Data v2 with HyperAgent parser + per-mode failure diagnosis · re-sign counter
- ✅ **v0.15/v0.16/v0.17** — shingle-overlap restart + FM-2.6 detector (**first real TP**: FM-2.1 F1 0.50) · signed fleet webhooks · routing-placeholder filter (FM-1.3 FP 2 → 0)
- ✅ **v0.18–v0.23** — `attribute --explain` (auditable fusion arithmetic) · `verify --all` store gate · `verify --all --json` + `fleet --json` machine outputs · `--since` time windows on every store command · scheduled fleet digest pattern
- ✅ **v0.24–v0.29** — multi-label evaluation (set-based P/R/F1; FM-2.1 F1 0.96 on real annotated data) · replay `--html` A/B page · terminal sparkline · bounded webhook retries · doc-artifact pipeline
- ✅ **v0.30** — FM-2.6 action-continuity guards (real-data precision 0.07 → 0.33, F1 0.12 → 0.40 at unchanged recall) · bounded prose analysis: megabyte-turn DoS fixed (>20 s → ~1 ms)
- ✅ **v0.31** — outcome-level verification analysis (FM-3.2 first nonzero on real data: P 0.54 · R 0.64 · F1 0.58 — completion claim + zero outcome signals in the record = unchecked claim)
- ✅ **v0.32** — `diff --json` with per-entry divergence scores: CI can assert "worst mutation still >0.9 similar" instead of eyeballing previews
- ✅ **v0.33** — query DSL: `query "success == false and task contains 'fix'"` — recursive-descent expression language over the store, eval-free, `--json`
- ✅ **v0.34** — fleet watch loop: `fleet --watch SECONDS --digest-dir DIR` writes rotating JSONL trend snapshots (`--iterations` for cron)
- ✅ **v0.35** — 95% Wilson intervals on every benchmark P/R (FM-2.1 P 0.93 [0.69, 0.99]) — uncertainty built into the leaderboard, not a footnote
- ✅ **v0.36** — Mermaid export: `report --mermaid` renders attributed traces as sequenceDiagrams for READMEs/PRs
- ✅ **v0.37** — MCP server: `approximately mcp` speaks JSON-RPC 2.0 over stdio — agent failures queryable from Claude Desktop, Zed, any MCP client (zero deps)
- ✅ **v0.38** — cycle-grade repetition: FM-1.3 recall 0.14 → 0.71 at precision 1.00 on multi-agent gold data · prose-repeat DoS fixed (36.6 s → 0.23 s, 157×)
- ✅ **v0.39** — `bisect FAILED SUCCESS`: first *material* divergence between two runs (timestamp-noise floor, `--json` for CI)
- ✅ **v0.40** — `fleet --trend`: per-day fleet analytics over the digest history — sparkline + Theil-Sen verdict as a CI gate
- ✅ **v0.41** — `doctor`: store health check — corrupt records, ledger tamper, stale locks, digest gaps (exit 1 = CI gate)
- ✅ **v0.42** — `query --stats`: aggregate any DSL selection — counts, failure rate, mode totals, means
- ✅ **v0.43** — attribution regression gate: gold-corpus P/R/F1 floors enforced by a CI job — detector refactors can't silently degrade attribution
- ✅ **v0.44** — adversarial-input fuzz round: seeded garbage through every parser boundary (DSL, doctor, MCP lines, prose) — documented errors, bounded time
- ✅ **v0.45** — README walkthrough tests: advertised commands run in CI with their promised outputs
- ✅ **v0.46** — MCP server grows to 9 tools: bisect, doctor, fleet trend, and query stats — full CLI parity over stdio
- ✅ **v0.47** — `demo --scenario loop`: a crew stuck in an args-evolving cycle only the cycle detector can catch
- ✅ **v0.50** — `approximately explain FM-x.y`: per-mode deep dives with a live detector bridge (MCP grows to 10 tools) · the attribution gate ships as `bench-gate` + a reusable GitHub Action · per-agent identity (`Step.agent`) with the `stats --by-agent` scoreboard · adversarial round: markdown fence-breaking fixed, NaN floors refused, agent names proven injection-safe · `verify --all --strict/--quiet` policy gates · [docs/RECIPES.md](docs/RECIPES.md) cookbook
- ✅ **v0.51** — runner-up hypotheses render in HTML/Markdown reports · `doctor` flags legacy `meta['agent']` identity with the migration hint · releases are fully automatic (autotag on version bump → GitHub Release with notes + artifacts)
- ✅ **v0.52** — MCP `bench_gate` tool: CLI parity over stdio (11 tools) · `fleet --top-agents N` snapshot window · fuzz round 3: two real crashes fixed (digest shape, string floors) · TUTORIAL covers explain / agents / bench-gate
- ✅ **v0.57** — runner-up hypotheses in HTML reports gain collapsible per-mode fixes ("if it was actually…")
- ✅ **v0.58** — the synthetic bench corpus is agent-stamped: CI fixtures exercise Step.agent paths on every run
- ✅ **v0.59** — `attribute --min-confidence X`: tunable admission floor for noisy environments (can only raise, never lower)
- ✅ **v0.60** — the recidivist filter: `stats --by-agent --min-failed N` / MCP `scoreboard.min_failed` surfaces repeat-offender agents in one query
- ✅ **v0.61** — `verify <id> --json`: the six-exit-code integrity ladder as machine-readable verdicts for CI
- ✅ **v0.62** — one verdict payload everywhere: MCP `verify` returns the full ladder object (finals, rollback, ledger) and supports keyed traces; wrong-key no longer masquerades as TAMPERED
- ✅ **v0.63** — MCP `cluster` (13 tools): recidivist failure modes + agents over stdio, with `min_size`, `by_agent`, expression filter
- ✅ **v0.64** — fuzz round 4 + bounded key-file reads + **Windows save correctness** (bounded-replace survives reader clashes; daemon-reader test hygiene; CI stall watch-dogs)
- ✅ **v0.65** — supply-chain hardening: all CI actions SHA-pinned; new `security` job (bandit clean + secret scan)
- ✅ **v0.66** — per-select query memoization: repeated heavy fields (mode) run detectors once per trace, not once per mention; third perf-gate
- ✅ **v0.67** — MCP `similar` + `drift` (15 tools): alignment-nearest runs and PSI behaviour drift over stdio
- ✅ **v0.68** — MCP `counterfactual` + `predict` (17 tools): leave-one-out root cause and failure-precursor probability over stdio
- ✅ **v0.69** — MCP `context` + `curve` (19 tools): budgeted-runtime forecasts and recall-vs-budget sweeps over stdio
- ✅ **v0.70** — docs catch-up: 19-tool inventory in ARCHITECTURE/TUTORIAL, new `similar`/`drift` recipes in RECIPES
- ✅ **v0.71** — pydantic-ai adapter (#6): post-hoc message transcription, zero framework imports, both Usage eras
- ✅ **v0.72** — Google ADK adapter (#7): post-hoc event transcription, control events skipped, usage_metadata tokens
- ✅ **v0.73** — query DSL `tools contains 'deploy'` / `errors >= 1`: action-side fields in the eval-free grammar
- ✅ **v0.74** — CLI `--json` for `similar`/`drift`/`counterfactual`/`predict`: CLI and MCP render the identical payload from shared constructors
- ✅ **v0.75** — analyst annotations: append-only sidecar notes (chain untouched) across CLI / MCP / reports, 20 tools
- ✅ **v0.76** — fuzz round 5: query fields, payload constructors, annotations sidecar — all contained
- ✅ **v0.77** — bench-gate JUnit export: `--junit PATH` renders one testcase per guarded floor for CI reporters
- ✅ **v0.78** — fleet watch posts the HMAC-signed summary every cycle (`--webhook`); delivery failure warns, never stops the loop
- ✅ **v0.79** — annotations hygiene: `merge` carries the sidecar (rename-aware, deduped), `doctor` tallies unreadable lines
- ✅ **v0.80** — `context --json` / `curve --json`: CLI and MCP render the identical budget-forecast payloads
- ✅ **v0.81** — `fleet --watch --alert-worse-than RATE`: webhook pages only on signal (worsening trend or rate breach); recording never stops
- ✅ **v0.82** — docs: 20-tool inventory + quiet-alerting watch recipe
- ✅ **v0.83** — per-tool rollup: `stats --by-tool` / MCP `scoreboard.group_by` answers "which tools attract the errors?"
- ✅ **v0.84** — counterfactual root-cause card in HTML/Markdown reports (affordance-gated for long traces)
- ✅ **v0.85** — `bench-gate --json` / `merge --json`: structured output for the remaining CI-facing commands
- ✅ **v0.86** — MCP resources surface: browse traces + annotations as resources; one dynamic version across CLI/API/MCP
- ✅ **v0.87** — fuzz round 6: resources, group_by, alert threshold, merge sidecar — all contained
- ✅ **v0.88** — CI covers every Python it claims: 3.10/3.11 join the matrix (audit fix)
- ✅ **v0.89** — MCP `anomalies` + `diff` (22 tools): latency outliers and structural trace forensics over stdio
- ✅ **v0.90** — MCP `regression_test` (23 tools): an agent mints its own self-contained pytest guard from a failure
- ✅ **v0.91** — MCP `metrics` (24 tools): Prometheus exposition of store health, per-agent optional
- ✅ **v0.92** — docs: count-proof tool inventories (grouped by concern, `tools/list` as authority)
- ✅ **v0.93** — attribution 7× faster (difflib upper-bound pruning, zero verdict drift; bench-gate caught the first attempt's regression)
- 🔜 **next** — community feedback, more adapters, judge-distillation recipes

Ten-minute walkthrough: [docs/TUTORIAL.md](docs/TUTORIAL.md) · task cookbook: [docs/RECIPES.md](docs/RECIPES.md) · full design document: [docs/PLAN.md](docs/PLAN.md) · module map: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Contributing

Issues and PRs welcome. Good first issues: more framework adapters, exact-tokenizer integrations beyond tiktoken, per-serving-stack judge-distillation recipes.

## Citation

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
