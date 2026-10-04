# approximately

[![CI](https://github.com/B1ueMu3ic4m/approximately/actions/workflows/ci.yml/badge.svg)](https://github.com/B1ueMu3ic4m/approximately/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/approximately)](https://pypi.org/project/approximately/)
[![Python](https://img.shields.io/badge/python-3.9%2B-blue)](https://pypi.org/project/approximately/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

**Approximate memory, exact accountability.**

<p align="center">
<b>Free & open source · Zero dependencies · MIT · Python 3.9+ · pip install approximately</b>
</p>

> **v2** — a production-stable toolkit: 40 MCP tools (+resources), 7 framework
> adapters, MAST attribution with a gated quality floor, tamper-evident evidence,
> pipeline quality gates (`ci`), fleet monitoring with quiet alerting, and
> 1,600+ tests across a 15-job CI matrix.  Semver with teeth: major for big or
> breaking updates, minor for features, patch for fixes.

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
5. **Circulate** — export runs as OpenAI transcripts, lossless native, or OTLP spans for Jaeger/Tempo/Honeycomb; import any of them back; or point `approximately spool` at a directory and let the store feed itself

<details>
<summary><b>🔧 Developer quickstart (2 commands + 5 lines)</b></summary>

```bash
pip install approximately
approximately demo        # 30-second tour: a scripted agent that fails in classic ways
python -m approximately demo   # same door, module form: a scripted agent that fails in classic ways
approximately demo --scenario loop             # multi-agent cycle: only the cycle detector catches it
approximately demo --scenario verification    # unchecked claim: FM-3.2 end to end
approximately demo --scenario multi-agent   # researcher/writer crew: information withholding

# or run the MCP server from a container (zero deps, stdio)
docker build -t approximately .
docker run -i --rm -v "$PWD/agents:/agents" approximately mcp --store /agents/store
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

# the gate loop: wire CI, record with measured tokens/latency, enforce
approximately init                            # workflow + price table + .gitignore
approximately ci --store .agents-store \      # exit 1 fails the build
  --max-failure-rate 0.3 --max-p95-latency-ms 15000
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
| 🩺 `status` | One-glance ops overview: store health, top failure modes, triage tallies, last failing trace — `--json` for dashboards | `approximately status` |
| 📼 Flight recorder | Zero-dependency recording of every agent step — including inter-agent messages — any framework | `Recorder` / adapters |
| 🔍 Failure attribution | **All 14 MAST modes** covered by rule detectors; Bayesian fusion ranks verdicts by MAST base rates × evidence likelihood | `approximately attribute` |
| 🛡️ Tamper-evident evidence | Per-step hash chain + optional HMAC; `verify` detects edits, the ledger catches **rolled-back** traces, and `verify --all` gates a whole store in CI | `approximately verify [--all]` |
| 🧩 Fleet merge | Union another team's store, refusing broken evidence; id conflicts via skip/replace/rename | `approximately merge <source>` |
| 🗺️ Fleet dashboard | All your stores on one page: failure rates, trend sparklines, top modes, broken ledgers | `approximately fleet <dir>... --fleet-html` |
| 🔔 Fleet alerts | HMAC-signed JSON webhooks when a store's trend turns worse — receivers authenticate alerts like evidence | `approximately fleet --webhook URL` |
| ⏱️ Latency anomalies | Median/MAD modified z-score — flags slow *and* fast outlier steps without being fooled by tails | `approximately anomalies <trace>` |
| 🧱 Result bloat | The third meter: result character length — a tool dumping a 40k-char wall into the context can be cheap in tokens and still eat the window; composition + a truncation what-if price the fix | `approximately anomalies <trace> --results` / `context <trace> --composition --truncate-results 2000` |
| 🔁 Step-level replay | Verify fixes without re-running the task; A/B compare original vs patched executors | `approximately replay --patched` |
| 🧪 Regression guards | Failed runs become pytest tests that live in CI | `approximately test` |
| 📉 Context budgeting | "Where does a shrinking budget start losing facts?" — guarded in CI | `approximately context` / `test --budget` |
| 🎯 Budget optimizer | Binary-searches the **smallest context window that keeps recall ≥ target** | `approximately optimize` |
| 🔎 Recidivist clustering | Cross-run statistics of your systematic failure modes | `approximately cluster` |
| 📈 Failure-rate trends | "Is the agent getting better or worse?" — sparkline + robust Theil–Sen verdict in every batch report | `approximately report --all` / `stats --trend` |
| 🚀 Project scaffold | An instrumented agent project with guards, runnable in seconds | `approximately new myagent` |
| 🚦 Repo gate wiring | `approximately init` wires the CI quality gate into the repo you already have — workflow, price table, .gitignore; idempotent, nothing overwritten without --force | `approximately init` |
| 💸 Live budget rails | Token and dollar ceilings enforced DURING the run — the `ci` gate settles accounts after, a Budget stops the burn mid-episode: stamp the breach, warn once, or raise; unpriced models never silently count as $0, and the exit stamp is signature-covered | `Recorder(task, model, budget=Budget(tokens=50_000, usd=2.0, prices=prices, on_exceed="raise"))` |
| 🧾 Evidence packs | One trace's complete case in a single tamper-evident zip — record with the integrity chain, postmortem, annotations, chain verdict, and a sha256 manifest anyone can recompute | `approximately evidence <trace> case.zip` |
| ⚖️ Deployment compare | Baseline vs candidate store: new failure modes, rate/token/spend deltas — `--fail-on-new-modes` fails the build when this deployment fails in a way the last one never did | `approximately compare --baseline prod-a --candidate prod-b --fail-on-new-modes` |
| 🗜️ Digest drain | A 10s watch writes 8,640 snapshot lines a day and the trend only reads the day's final state — `--compact-digests` collapses each day to that line, and the watch drains itself on start and at midnight | `approximately fleet --compact-digests --digest-dir d` |
| 🧾 Offboarding archive | One command turns the whole store into per-trace evidence packs plus a recomputable index — the store can leave the machine | `approximately evidence --all archive/` |
| ✅ Pack verification | The reviewer's side of the pack: recompute every manifest hash and the chain inside, then TRUSTED or REFUSED — no tooling beyond the zip required | `approximately evidence --verify case.zip` |
| 🔮 Failure precursor | Early warning mined from your own history: "runs like this fail Z% of the time" | `approximately predict` |
| 🧬 Trajectory alignment | Needleman-Wunsch over action sequences — find runs with the same *shape*; `--agent` aligns one participant's stream instead of the interleaved multi-agent run | `approximately similar <trace> --agent researcher` |
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
| 🔎 Query DSL + stats | Select traces with an expression — or aggregate the selection: counts, failure rate, mode totals, means. Derived fields: `max_latency` (slowest timed tool call), `failed_tools` / `failed_agents` (names behind errored calls) | `approximately query "failed_tools contains 'search' and success == false"` |
| 📖 Mode explainer | "What does FM-1.3 mean *for my agent*?" — definition, published share, the detectors watching it, engineering fixes | `approximately explain FM-1.3` |
| 👥 Agent scoreboard | Who did what in a multi-agent run: steps, tokens, errors, and the failure rate of traces each agent touched | `Recorder(agent="researcher")` + `approximately stats --by-agent` |
| 📥📤 Log interop | Logs already on disk become tamper-evident traces — and traces export back out as OpenAI chat JSONL, lossless native, or OTLP spans for tracing backends; roundtrips restore ids | `approximately import logs/*.jsonl` · `approximately export out.otlp.json --format otel` |
| 🐢 Slowness & token burn | Per-tool latency AND token baselines per trace and fleet-wide, burn/spend trends over days, `--alert-anomalies` / `--alert-tokens` paging — slow or expensive runs are failures too | `approximately anomalies --all --tokens` |
| 💰 Spend is a signal | Adapters/OTLP capture real usage; per-model prices turn tokens into a per-store spend estimate, `--fail-over` alarms in CI, `--alert-spend` pages the watch | `approximately stats --prices prices.json --fail-over 50` |
| 🚦 CI quality gates | One command composes the ceilings (failure rate, p95 step latency, tokens, estimated spend, stamped budget breaches) into a pipeline-native verdict: exit 0 pass, 1 breach, 2 misconfiguration — an empty store is refused, a gate over zero runs proves nothing. `--format junit` renders natively in GitHub Actions / GitLab | `approximately ci --max-failure-rate 0.2 --max-p95-latency-ms 8000 --max-budget-breaches 0 --format junit` |
| 🧹 Retention by count | `clean --max-traces N` keeps only the newest N runs — an age cap alone lets one busy afternoon accumulate a thousand records forever; both caps compose, dry-run stays honest | `approximately clean --keep-days 30 --max-traces 500` |
| 🔌 MCP server | The whole toolkit as a Model Context Protocol stdio server (40 tools and counting — the committed [mcp-tools.json](docs/mcp-tools.json) mirrors it; `tools/list` is authoritative) — query failures and agent scoreboards from any MCP client | `approximately mcp` |
| 🧪 Attribution quality gates | Gold-corpus + large-n synthetic floors run in CI — a detector refactor that degrades P/R fails the build | `python scripts/bench_gate.py [--synth]` |
| 🚦 Gate as a GitHub Action | The same attribution gate as a drop-in action for your own repo's workflow | `uses: B1ueMu3ic4m/approximately@v0` |

**See it before you trust it** — real rendered artifacts, generated by the tool itself: [postmortem report](docs/artifacts/report.html) · [batch index with failure-rate trend](docs/artifacts/index.html) · [budget-vs-recall curve](docs/artifacts/curve.html) · [fleet dashboard](docs/artifacts/fleet.html) · [MAST-Data leaderboard](docs/artifacts/leaderboard.html) · [multi-label leaderboard](docs/LEADERBOARD.md) (regenerate with `python3 scripts/make_docs_artifacts.py`).

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

The per-version history lives where GitHub keeps it: [CHANGELOG.md](CHANGELOG.md)
and the [Releases page](https://github.com/B1ueMu3ic4m/approximately/releases) —
this README stays lean. The delivered capability eras, in order:

- **See the run** — flight recorder, concurrent-safe store, tamper-evident evidence + `verify`, `doctor`
- **Explain the failure** — MAST rule + judge detectors, Bayesian fusion, conformal attribution, `attribute --explain`
- **Prove the fix** — replay, regression guards, `bisect`, structural diff, failure-to-test pipeline
- **Ask anything** — query DSL + stats, reports (HTML/Mermaid/SARIF/Prometheus), fleet dashboards, trend gates
- **Learn from real data** — MAST-Data annotations + benchmarks, prose detector family, leaderboard, distillation
- **Meet agents where they are** — 7 framework adapters, 32-tool MCP server, OpenAI/OTel/native import-export
- **Slowness is a signal** — per-tool & fleet latency baselines, anomaly surfacing in reports and CI

What ships next is decided item by item in [docs/PLAN.md](docs/PLAN.md).

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
