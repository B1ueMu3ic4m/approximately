# Changelog

## 0.35.0 — 2026-09-17

- **Wilson score intervals on benchmark metrics**: every per-mode
  precision and recall in `benchmark` output (text, `--multi-label`,
  and the HTML leaderboard) now carries a 95% Wilson interval
  (Wilson 1927) — point estimates on n=27 lie, and the interval
  communicates that honestly (FM-2.1's P 0.93 reads as [0.69, 0.99];
  FM-3.2's R 0.64 as [0.36, 0.85]). Intervals stay inside [0, 1] and
  do not degenerate at 0 or n successes.
- 9 new tests; suite at 573 passing.

## 0.34.0 — 2026-09-17

- **Fleet watch loop**: `fleet STORES --watch SECONDS --digest-dir
  DIR [--iterations N] [--keep-days DAYS]` — polls the fleet and
  appends one JSONL snapshot per cycle (per-store trace counts,
  failure rates, trend verdicts, worsening flags) to daily
  `digest-YYYYMMDD.jsonl` files with automatic retention rotation.
  `--iterations` makes it cron-friendly (N snapshots then exit);
  SIGTERM/Ctrl-C stop cleanly. The documented digest pattern
  (docs/FLEET-DIGEST.md) is now a shipped command.
- 8 new tests; suite at 564 passing.

## 0.33.0 — 2026-09-17

- **Query DSL**: `query "success == false and task contains 'fix'"`
  — a small expression language over the trace store: recursive-
  descent parser (precedence `or` < `and` < `not`, parentheses), 9
  trace fields (`id task success model created steps tokens duration
  mode`), 7 operators (`== != >= <= > < contains startswith`), and
  `mode == FM-x.y` membership against detected failure modes.
  `--json` emits full records. No `eval`: the parser produces
  comparison closures only; expressions are depth-capped (50) and
  length-capped (4000 chars) against parser stack attacks.
- 23 new tests; suite at 557 passing.

## 0.32.0 — 2026-09-17

- **`diff --json` + per-entry similarity**: every mutated entry in
  the Needleman-Wunsch edit script now carries a character-similarity
  score of the paired step results (gaps score 0.0), and
  `TraceDiff.divergences()` ranks differing entries worst-first.
  `diff --json` emits counts, alignment similarity, and all differing
  entries with scores — CI can now assert "the worst mutation is
  still >0.9 similar" instead of eyeballing previews.
- 7 new tests; suite at 534 passing.

## 0.31.0 — 2026-09-17

- **Outcome-level verification analysis (FM-3.2)**: new
  `ProseOutcomeVerifyDetector` reads the execution record, not the
  vocabulary — a closing message that asserts resolution with zero
  outcome signals anywhere in the record (no test summary, pass/fail
  count, or error trace) is an unchecked claim. Completion-claim
  vocabulary deliberately excludes execution-shaped language ("the
  script executed successfully" reports a run, it does not claim the
  outcome is good). First nonzero FM-3.2 score on real MAST-Data:
  P 0.54 · R 0.64 · F1 0.58 (was 0.00/0.00/0.00); corpus sample
  F1 0.29 → 0.43.
- 8 new tests; suite at 527 passing.

## 0.30.0 — 2026-09-17

- **FM-2.6 action-continuity guards**: the thought/action divergence
  detector now suppresses three continuation shapes before flagging —
  prompt-scaffold echo (no action to diverge), entity-token continuity
  (path/stem/bare-name variants the raw substring test missed:
  `from_file()` ↔ `grep "def from_file"`, `Permutation` ↔
  `permutations.py`), and thought-context continuity (plan says
  "check the backend docs", action opens `backends/`). On real
  MAST-Data: FM-2.6 precision 0.07 → 0.33 (fp 14 → 2), F1 0.12 →
  0.40 at unchanged recall; corpus-level sample precision 0.30 →
  0.44. Confidence raised to the 0.7 rules-evidence floor.
- **Bounded prose analysis (security)**: stress testing exposed an
  algorithmic-complexity DoS — a single megabyte turn drove the
  identifier regex into O(n²) backtracking (>20 s per turn). All
  prose-family turn text is now whitespace-normalized and capped at
  8k chars; 1 MB adversarial turns analyze in ~1 ms.
- 9 new tests (guards + stress probes); 519 passing.

## 0.29.0 — 2026-09-17

- **Multi-label evaluation**: `convert-mast --multi-label` +
  `benchmark --multi-label` — set-based sample-averaged P/R/F1 over
  the full gold set; real MAST-Data run published (27 records):
  FM-2.1 P 0.93 · R 1.00 · F1 0.96
- **`replay --html`**: self-contained A/B replay page with per-step
  recorded-vs-replayed table, diverged rows highlighted, patched
  executor column
- **`stats --trend` terminal sparkline**; trend buckets in JSON

## 0.26.0 — 2026-09-17

- **`replay --html`**: self-contained A/B replay page — verdict badge,
  match rate, per-step recorded-vs-replayed (vs patched executor)
  table with diverged rows highlighted; executor output escaped

## 0.25.0 — 2026-09-17

- **Webhook bounded retry**: transport failures retry once with brief
  backoff; endpoint error codes (4xx/5xx) are definite answers and are
  not retried. urllib imports hoisted to module level for testability
- FM-2.3 prose derailment diagnosed structurally: keyword persistence
  on goal-drift golds means progress-level features are required;
  documented as deferred in docs/LEADERBOARD.md instead of fitted

## 0.24.0 — 2026-09-17

- **Docs artifacts pipeline** (`scripts/make_docs_artifacts.py`):
  regenerates real rendered pages (postmortem report, index with
  trend, budget-vs-recall curve, fleet dashboard) into
  docs/artifacts; README links them
- **Fixed**: `demo --store X` was accepted and silently ignored
  (demo recordings always landed in the default store)
- **Fixed**: `latest` was advertised in help text but never resolved
  by the trace loader

## 0.23.0 — 2026-09-17

- **`--since DAYS` time-window queries**: `TraceStore.list_traces`
  filters on the trace's own `created_at` (mtime fallback); `--since`
  reaches `stats`, `cluster` (composes with `--last`), `attribute
  --all` and `verify --all` — triage means "the last N days", and now
  every store command agrees
- Scheduled fleet digest pattern documented (docs/FLEET-DIGEST.md):
  GitHub Actions cron + signed webhook + receiver verification

## 0.21.0 — 2026-09-17

- **Restart-owns-opening-cycle precedence** (FM-1.3 precision): a
  repetition cycle anchored at the opening turn is a trajectory
  restart and belongs to the restart detector — FM-1.3 false
  predictions on the real benchmark: 2 → 0, FM-2.1 holds
  P 0.50 · R 0.50 · F1 0.50. LEADERBOARD run-history table extended
  (v2 → v6)

## 0.19.0 — 2026-09-17

- **`verify --all`**: batch integrity audit over a whole store —
  per-trace verdict lines (intact / unsigned / keyed / TAMPERED /
  rolled-back), broken-ledger surfacing, summary counts, exit 1 on
  any failure. The whole-store gate for CI nightlies and audit jobs

## 0.18.0 — 2026-09-17

- **`attribute --explain`** (`attributor.explain_fusion`): auditable
  fusion arithmetic — per detection, the MAST prior (probability +
  log-odds), the confidence's LLR, the fused score, and the ranked
  verdict line. A disputed ranking is now demonstrable, not asserted

## 0.17.0 — 2026-09-17

- **Routing-placeholder filter** (FM-1.3 precision): repeated harness
  transport lines (`Observation Editor->Planner: Observation`) no
  longer count as step repetition — repetition means repeated *work*.
  Benchmark v5: FM-1.3 false predictions 2 → 1, FM-2.1 holds
  P 0.50 · R 0.50 · F1 0.50
- **FM-3.2 outcome-level analysis deliberately deferred**: all 6 golds
  contain verification AND execution language; regex cannot cross the
  outcome-verification semantic gap on n=6 without gold-fitting —
  reasoning recorded in docs/LEADERBOARD.md

## 0.16.0 — 2026-09-17

- **Fleet webhooks** (`fleet.py` + `approximately fleet --webhook`):
  signed JSON fleet summaries to any notification endpoint — per-store
  trend verdicts, failure rates, ledger state, top modes; HMAC-SHA256
  body signature in `X-Approximately-Signature` when
  APPROXIMATELY_SIGNING_KEY is set. Composable with
  `--fail-on-worsening`; FM-3.2 outcome-level analysis deliberately
  deferred (documented in docs/LEADERBOARD.md)

## 0.15.0 — 2026-09-17

- **Shingle-overlap restart** (FM-2.1): character-trigram Jaccard
  between the opening turn and later turns catches paraphrased
  restarts SequenceMatcher misses (real gold: 0.28 ratio / 0.553 J);
  confidence 0.7 to clear the rules-labeler floor — the v0.14 run had
  the evidence and lost the prediction to the 0.6 < 0.7 floor gap
- **FM-2.6 prose detector**: thought/action entity divergence in
  Thought/Action-shaped turns
- **Benchmark v4**: first true positive on human-annotated data —
  accuracy 0.00 → 0.08, FM-2.1 P 0.50 · R 0.50 · F1 0.50, with the
  run-history table and the calibration lesson in
  docs/LEADERBOARD.md

## 0.14.0 — 2026-09-17

- **Prose detector family** (`prose.py`): five detectors over agent
  turns for chat-shaped trajectories — repetition, restart
  (opening-turn recurrence / task re-statement), keyword-loss
  derailment, absent verification language, insufficiency-then-proceed.
  Families are exclusive: prose traces run prose detectors only
- **MAST-Data v2** (`mastdata.py`): HyperAgent log-line schema parser;
  harness-boilerplate filtering; 2-signal-turn floor; yes-annotated
  behaviours force `success=False` (task correctness must not mask
  annotated failures — this had hidden every prediction). Real
  benchmark v2 published with per-mode structural diagnosis
  (docs/LEADERBOARD.md)
- **Re-sign counter** (`integrity.py`): every integrity block carries
  a monotonic resign_count; `verify` reports "re-signed Nx" — evidence
  provenance in the block itself

## 0.13.0 — 2026-09-16

- **Fleet trend alerts**: `survey()` computes the Theil-Sen verdict
  per store; the dashboard card shows the improving/stable/worsening
  badge and `--fail-on-worsening` exits 1 naming the degrading stores —
  the fleet page doubles as a CI gate
- **MAST-Data pipeline** (`mastdata.py` +
  `approximately convert-mast`): converts the MAST project's human
  annotations (arXiv:2503.13657) into labeled benchmark JSONL under
  three honesty rules — only detector-covered behaviours map, only
  single-label traces become rows, every exclusion is counted. First
  real-data run published in `docs/LEADERBOARD.md` with structural
  analysis: chat-shaped corpus vs tool-call-fingerprint detectors,
  accuracy 0.00 at n=13, printed as-is

## 0.12.0 — 2026-09-16

- **Fleet dashboard** (`fleet.py` + `approximately fleet <dir>...`
  `--fleet-html`): surveys any number of stores into one self-contained
  page — fleet KPIs (traces, weighted failure rate, broken ledgers),
  per-store failure-rate sparklines and top attributed MAST modes.
  Rule detectors only: a sweep needs no API key or network
- **Robust latency anomalies** (`anomaly.py` +
  `approximately anomalies <trace>`): modified z-score (Iglewicz &
  Hoaglin 1993) over the median absolute deviation (Leys et al. 2013)
  flags slow *and* fast outlier steps; MAD == 0 and small samples
  honestly yield nothing. Postmortem reports gain an anomalies card;
  nonzero exit for CI gates
- **Fixed**: `--store` placed *before* the subcommand was silently
  ignored (argparse subparser default clobbered the top-level value) —
  only the after-position worked. Both now parse correctly

## 0.11.0 — 2026-09-16

- **Evidence ledger** (`ledger.py`, opt-in via `APPROXIMATELY_LEDGER=1`):
  every save appends the trace's chain-final hash to an append-only,
  itself hash-chained ledger — `verify` now detects a trace file rolled
  back to an older *correctly-signed* snapshot (exit 4) and a broken
  ledger (exit 5). Closes the "hashes all check out but the state is
  stale" gap; threat-model limits documented in the module
- **Cross-store merge** (`merge.py` + `approximately merge`): fleet
  imports with evidence refusal — traces whose integrity fails
  (TAMPERED / wrong-key) are never imported; id conflicts resolve via
  `--on-conflict skip|replace|rename`; per-trace atomic saves keep an
  interrupted merge harmless

## 0.10.0 — 2026-09-16

- **LlamaIndex Dispatcher seam** (`contrib/llamaindex.py`): a
  duck-typed `BaseSpanHandler` for `llama_index.core.instrumentation` —
  structured spans (LLM prompt/completion, retrievals, tool calls,
  agent runs) with dropped spans becoming error steps carrying the
  exception; a finer layer alongside the callback seam
- **`benchmark --html` leaderboard**: renders a BenchmarkResult as a
  self-contained HTML page (KPI cards, per-mode F1-sorted table with
  clamped bars); dataset-supplied strings HTML-escaped, non-finite
  metrics clamp instead of leaking `nan`; unknown mode ids fall back
  to the OTHER label
- **Distillation recipes** (`docs/DISTILLATION.md`): per-serving-stack
  paths (Ollama, llama.cpp, vLLM LoRA, TGI, OpenAI fine-tunes) with the
  export -> train -> serve -> benchmark loop and honest per-mode
  expectations for small judges

## 0.9.0 — 2026-09-15

- **LlamaIndex adapter** (`contrib/llamaindex.py`): a duck-typed
  callback handler covering the `BaseCallbackHandler` protocol without
  importing llama_index — LLM calls, function calls (kwargs parsed
  across brace/paren serialisations), agent steps, retrievals and
  exceptions land in the trace. Version-tolerant (enum-or-string event
  types, defensive payload lookup) and exception-guarded
- **HMAC key-ID + rotation counter** (`integrity.py`): keyed blocks now
  stamp a key fingerprint and a monotonic rotation count. `verify`
  gained an honest new verdict — a trace signed by a *different* key
  reads `wrong-key` (locked, not broken) instead of the old false
  `TAMPERED` accusation; forgery via an attacker's own key still never
  verifies as intact. Old blocks keep verifying (back-compat tested)

## 0.8.0 — 2026-09-13

- **AutoGen adapter** (`contrib/autogen.py`): two capture seams for
  AutoGen v0.4+ — an `AutoGenEventHandler` that converts
  `autogen_core.events` objects (the same seam AutoGen Studio consumes)
  into recorder steps, and a transparent `RecordingChatCompletionClient`
  proxy that records every `create()` at the model boundary independent
  of logging config. Version-tolerant and exception-guarded: unknown
  future events are ignored and a failing recorder cannot break a run
- **Failure-rate trend in the HTML index** (`report.py`): `report --all`
  now renders a sparkline (inline SVG, still no JS/CDN) of failure rate
  per time bucket with an improving/stable/worsening verdict based on a
  Theil–Sen slope judged relative to the series' own mean level — one
  anomalous bucket cannot drag the estimate, and 2-point jitter on a
  60% rate reads as noise rather than a trend
- Audit round: **all 14 C-complexity blocks refactored to B or better**
  under a strict xenon bar (`--max-absolute B`, stricter than the CI
  gate) — attribution, judge, repair, integrity, toolscan, curve,
  report, detectors, context forecast and both SDK adapters; the full
  suite guarded every refactor
- Security fuzzing of the new surfaces: poisoned event objects, hostile
  logger names, handler lifecycle leaks, `<script>` smuggling through
  sparkline values, malformed trend rows. Found and fixed two real
  bugs: `cluster.trend` crashed (OverflowError) on out-of-range
  timestamps, and the sparkline could emit `nan` SVG coordinates when
  values spanned ±1e308

## 0.7.0 — 2026-09-10

- **Streaming reliability monitor** (`streaming.py`): live failure-risk
  estimation over in-flight runs — precursor probability, repetition
  velocity (sliding window), verification debt — fused by weighted voting
  with hysteresis so levels cannot flap. `observe(trace)` after every
  tool call; O(window) per observation.
  The level-machine hysteresis bug (dead branch, caught by its own test)
  was fixed before merge.
- **Concurrent-safe trace store**: saves are atomic (temp + os.replace)
  and same-id writes serialize via a per-id lock file with stale-lock
  recovery — multiple agents recording to a shared store is now the
  supported deployment. Readers never observe a partial write (tested
  with a polling reader across 30 saves).
- Audit round: stale-lock recovery and lock-wait paths now tested
  (store.py coverage 90% → 95%); zero-dependency claim re-verified by
  AST scan; bandit/mypy/xenon all clean

## 0.6.0 — 2026-09-09

- **Prometheus metrics export** (`metrics.py` + `approximately metrics
  --prometheus`): runs_total/failures_total/failure_rate/steps_average
  and per-MAST-mode counters, with per-spec label escaping — agent
  reliability on the same dashboards and alerts as every other service


- **Minimal-repair search** (`repair.py` + `approximately repair`):
  greedy prescription search over an honest intervention vocabulary
  (drop-duplicate calls, insert verification after unverified mutating
  calls); every prescription is validated by re-attribution, and modes
  that need agent-level changes are reported as unrepairable instead of
  being faked by trace surgery


- **Structural trace diff** (`diff.py` + `approximately diff <a> <b>`):
  Needleman-Wunsch **traceback** over two runs — every tool call
  classified equal/mutated/deleted/inserted. The classic workflow: diff
  the failed run against the last successful one; the first `~` is where
  behavior broke. Alignment traceback shares the scoring of align.py
  (similarity consistent between the two modules, tested).

## 0.5.0 — 2026-09-08

- **Behavior-drift detection** (`drift.py` + `approximately drift`):
  Population Stability Index over action structure tokens between an
  older baseline window and a recent window (<0.1 no shift, >0.25
  significant) — catches prompt/model/tool changes before failures spike


- **Counterfactual root-cause analysis** (`counterfactual.py` +
  `approximately counterfactual`): do(step=∅) leave-one-out intervention
  experiments over every detected step; classifies root causes vs
  symptoms vs distributed causes, with a causal ranking by eliminated
  modes. Found and fixed a real aliasing bug during its own tests:
  ``Trace.add`` re-assigns ``step.index``, so the do-trace must deep-copy
  steps or the original trace silently renumbers itself.


- **Conformal attribution** (`calibration.py` + `calibrate`): split-
  conformal prediction sets over MAST modes with a distribution-free
  coverage guarantee (alpha configurable; the only assumption is
  exchangeability). Ambiguous runs honestly widen the set.
- **Temperature calibration**: NLL-fitted temperature scaling (Guo et
  al. 2017 criterion — deliberately not ECE, which collapses to a
  degenerate temperature on separable sets); ECE reported as a metric.
- `score_modes`: per-mode fusion score surface, consumed by calibration
  and conformal layers.

## 0.4.0 — 2026-09-08

- **Trajectory alignment** (`approximately similar`): Needleman-Wunsch
  global alignment over normalized action sequences — identity tokens
  score full matches, structure tokens half credit; [0,1] and symmetric
- **Failure-precursor prediction** (`approximately predict`): n-gram
  early warning mined from your own store (structure-token prefixes,
  Laplace-smoothed conditionals, support-capped log-odds); unseen
  prefixes honestly score 0.5
- **SARIF 2.1.0 export** (`attribute --sarif out.sarif`): agent failures
  as GitHub code-scanning alerts via upload-sarif
- **MCP tool-poisoning scanner** (`scan-tool`): invisible characters,
  bidi attacks, homoglyph script mixing, injection phrasing — verdicts
  clean/suspicious/malicious
- **HMAC key rotation** (`rotate --old-key-file --new-key-file`):
  re-key signed traces, refused when the old key no longer verifies

## 0.3.2 — 2026-09-08

- Code-health gate: xenon in CI (blocks D/F-grade complexity);
  replay/Clarification/Withholding/NoTermination refactored below it

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
