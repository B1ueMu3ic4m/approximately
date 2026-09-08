# Changelog

## 0.3.2 — 2026-09-08

- **Bayesian evidence fusion**: detections are scored as
  `log(prior_odds) + Σ log-likelihood-ratio(confidence)` with MAST base
  rates as priors (add-one smoothed). Independent weak evidence now
  accumulates; strong evidence beats a common-mode prior; a 0.9-confidence
  rare-mode detection honestly loses to a 0.8 common-mode one (correct
  base-rate correction, tested).
- **`approximately optimize <trace>`**: binary-searches the smallest
  context budget that keeps effective recall ≥ target (20k-step traces:
  ~10 probes instead of a full sweep).
- Untrusted trace JSON parsing hardened: malformed records raise
  ValueError (store warns and skips) instead of leaking
  AttributeError/TypeError; 60+ fuzz payloads pin the contract.

## 0.3.1 — 2026-09-08

- **Tamper-evident evidence chains**: every saved trace carries a per-step
  sha256 hash chain; `approximately verify <trace>` detects and localizes
  any post-hoc edit (incidents/compliance grade postmortems)
- Security hardening: path-traversal blocks in the trace store and the
  scaffold name validator; threat model published (docs/SECURITY.md)

## 0.3.0 — 2026-09-08

- **Complete MAST rule coverage: all 14 failure modes detected offline**
  (FM-1.2 role violations via role_tools conventions; FM-1.4 lost
  references — quoting identifiers that never appeared earlier)
- Multi-agent recording: `Recorder.message(from, to, text)` message steps
- `approximately report --all` also writes every individual report so
  index links always resolve

- New rule detectors: FM-1.5 (unaware of termination: long-range loops,
  step-limit exhaustion), FM-2.6 (reasoning-action mismatch), FM-3.3
  (echo verification), FM-2.2 (fail to ask clarification), FM-2.4
  (information withholding), FM-2.5 (ignored peer input)
  — rules now cover 12 of 14 MAST modes
- `Recorder.message(from, to, text)` inter-agent message steps
- `approximately export-dataset`: labeled JSONL export for the benchmark
- `approximately report --all`: batch postmortem index page
- Every HTML report embeds a half-budget context-forecast card
- `approximately replay --patched`: A/B comparison summaries
- Optional exact token counting (APPROXIMATELY_EXACT_TOKENS=1 + tiktoken)
- PyPI publishing workflow (Trusted Publishing on v* tags)
- Community: PR/issue templates, CI-integration guide
    (docs/ci-integration.md), `replay --threshold`
- `approximately new <name>`: scaffold an instrumented agent project
  (recorder wired, guards included, runnable in seconds)
- `approximately stats [--json]`: store health at a glance
- `approximately attribute --all --json`: batch attribution for CI
- `report --all` writes missing individual reports (index links resolve)
- `curve --budgets` custom sweep list; `cluster --last N`; `py.typed`
- `demo --scenario multi-agent`: researcher/writer crew showcasing the
  message convention and FM-2.4/FM-3.1 detection live
- O(n log n) verification detectors (was O(n²) on verify-free traces);
  detector quality-floor suite; 20k-step stress test
- judge: compact trace now carries semantic step meta (mutating/verify/
  agent markers) so the judge can reason about verification failures
- store: stderr warning when a trace file is unreadable (was silent)
- `replay --patched`: A/B comparison summaries; `Recorder.fail` records
  latency; CONTRIBUTING.md, CITATION.cff, dependabot, CI concurrency

## 0.2.0 — 2026-09-08

- Framework adapters: LangChain/LangGraph, OpenAI Agents SDK, CrewAI
- Judge presets (strong/local) + `distill` SFT exporter (rules or teacher)
- `benchmark` command with per-mode precision/recall/F1 + MAST-Data loader
- `cluster` cross-trace recidivist clustering
- Budget regression guards (`test --budget --min-recall`)
- `curve` cost-vs-recall SVG reports + success scatter
- 122 tests, CI: 3 OS × 3 Python + judge-integration + contrib jobs

## 0.1.0 — 2026-09-08

- Flight recorder (Recorder, @agentstep), trace store
- MAST taxonomy (14 modes) + rule detectors + optional LLM judge
- Step-level replay, pytest regression generation, HTML postmortem report
- Context runtime: budgeted windows, pins, compaction, recall probes,
  budget forecasting
