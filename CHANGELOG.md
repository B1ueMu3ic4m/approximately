# Changelog

Generated from [docs/PLAN.md](docs/PLAN.md) — the single
source of truth. Newest first.

## v2.86.0

- the stamp reaches the scrapers and the spreadsheets: Prometheus entity renderings gain `approximately_{tool,agent}_breached_traces_total` beside `failed_traces` (both scorecards count breached runs the entity touched), and CSV export gains a `budget_breached` column per step row — a spreadsheet filters the burn without unpacking JSON. position-based CSV pins moved for the new column; the injection defense is pinned unchanged.

## v2.85.0

- the CI guide learns what the gate can do now: docs/ci-integration.md gains the quality-gate section — ceiling composition, `--max-budget-breaches`, the junit and step-summary renderings with the same exit codes, and the deployment compare's junit testcase. ARCHITECTURE's module map stops pretending budget.py doesn't exist. docs-only.

## v2.84.0

- the last two readers of the stamp: the agent scorecard gains `breached_traces` (parallel to failed_traces — a run the live rails stopped is a fact about every agent who touched it, the unattributed steps included), and `evidence --all`'s archive index carries `budget_breached` per trace, so a reviewer opening the offboarding archive sees which runs came home over budget without unpacking a single zip. webhook top-agent rows carry the column too.

## v2.83.0

- the breach count learns to trend: digest day-rows carried each store's budget_breaches since v2.72 and the trend section finally reads them — a Theil-Sen breach_trend verdict, a sparkline, and a day-table column, so "is the fleet burning more or less over time?" is a glance. the perf wall's two flaky-tonight budgets get the Night V remedy (spool 5s→8s, clean 2s→4s — Windows shared-runner variance, both green on rerun).

## v2.82.0

- fuzz 21 points the hostile probes at the surfaces the budget wave never touched — evidence packs, trace diff, clustering — and finds no holes; the pins keep it that way: keyed-pack verdict semantics (right key intact / wrong key wrong-key / no key keyed, sealed not broken), tampered and missing members named exactly, zero-step traces through packs and every scorecard, fifty identical failures collapsing to one cluster, self-diff stability. tests-only release (v2.66 precedent).

## v2.81.0

- the verdict reads well where humans look: `ci --format markdown` renders a step-summary table a pipeline can cat into $GITHUB_STEP_SUMMARY (gate / measured / ceiling / verdict, refusals as paragraphs, exit codes unchanged), and the fleet card now NAMES the agents the per-agent ceilings caught — v2.80.0's stamp carried the data, the card just reads it (summary, webhook payload and digest follow; "budget breach(es) — agents: researcher, booker").

## v2.80.0

- per-agent ceilings: a shared budget lets one runaway agent hide inside the group total — `Budget(per_agent={"researcher": 10_000}, ...)` meters each named agent's tokens beside the global ceilings. trips independently, names the agent in the error ("budget exceeded: agent 'researcher' 1,500/1,000 tokens"), warns the same way, and lands per-agent meters in the stamp (`meta["budget"]["agents"]`). the multi-agent story gets the same breaker the single run had.

## v2.79.0

- the verdict reaches the agent side and the pulse: the MCP doctor tool gains `fix` (an agent harness can repair its own store through the same door the CLI uses — hygiene removed, corrupt records quarantined, bytes preserved), and `status` carries the budget-breach count in both shapes (json field + a text line: "budget breaches: 1 run(s) the live rails stopped"). the MCP surface is documented back into docs/mcp-tools.json.

## v2.78.0

- fuzz 20 audits the new surfaces and finds three real meter lies: a NEGATIVE price paid the run to burn (usd drifted to -1,500 while the ceiling sat silent), negative tokens ran the meter backwards (500 charged, 400 "refunded", ceiling never tripped), and float tokens drifted the meters. prices must now be finite and non-negative; token counts must be non-negative ints — and budgeted recorders validate BEFORE the step lands (an impossible input never enters a trace; a real breach records first, then trips). plus quarantine/junit hostile-input pins (unicode+quote names, clash storms, pathologically named tasks).

## v2.77.0

- the breaker gets its chapters: RECIPES 22 walks the live budget end to end (arm the rails, read the stamp everywhere: gate, fleet, retention, postmortem) and TUTORIAL 12 tells the looping-agent story with the Live budget card as the receipt. docs-only — the seven releases before it wrote the code, this one teaches it.

## v2.76.0

- the deployment gate speaks junit: `compare --format junit` mirrors the one gateable verdict (new failure modes under --fail-on-new-modes) as a failing testcase, with rate/token/spend deltas as informational cases; refusals stay exit 2 as <error> testcases. verdicts are mirrored, never invented. the perf-gate wall grows to 21: budget rails (2k budgeted runs), junit render (2k traces), and quarantine (doctor + move over 220 files) earn their budgets like every surface before them.

## v2.75.0

- quarantine for the unreadable: `doctor --fix` moves corrupt record files into `<store>/.quarantine/` with a jsonl manifest (what, when, why) — the bytes are preserved for forensics, never unlinked, and the store stops re-reporting the same poison on every scan. name clashes are suffixed, vanished files skipped, and the parse error travels with the record. a quarantined store reports healthy again.

## v2.74.0

- the breaker's receipt in the postmortem: a Live budget card in report.html — what the rails metered (tokens, est. spend, unpriced tokens), what the ceilings were, and whether the breaker tripped. best-effort like every card: no stamp, no card; poison meta renders nothing. evidence packs carry it and stay TRUSTED. the budget loop now closes end to end: record → gate → fleet → retention → postmortem.

## v2.73.0

- the stamp survives housekeeping: `clean --keep-breached` — runs the live Budget rails stamped as breached survive retention no matter their age or the count ceiling, because housekeeping must not destroy breach evidence before the postmortem reads it. unreadable files are never kept by the guard (a poison file is not evidence); the count cap skips past a breached trace to the next victim instead. the predicate moved to store.stamped_breach, one copy behind every surface. the init workflow template now gates with `--max-budget-breaches 0` out of the box.

## v2.72.0

- the fleet sees the stamp: a live Budget breach now surfaces in the store summary, the webhook payload, the HTML card ("budget breach(es) — the live rails stopped these runs"), and alerting via `--alert-budget-breaches N`. one predicate (`fleet._budget_breaches`) feeds every surface, the ci gate included. plus a real alerting fix: an anomaly/token/spend threshold WITHOUT a failure threshold used to page healthy stores every cycle — the rate clause was `failure_rate >= (None or 0.0)`, always true. healthy fleets are quiet now, as the docstring always promised.

## v2.71.0

- the gate speaks junit: `ci --format junit` renders the gate rows as native CI annotations — one testcase per gate, a <failure> element per breach, and config refusals become <error> testcases so GitHub Actions and GitLab show WHY the gate refused. exit codes never move. plus `--max-budget-breaches N`: the live Budget rails' stamped verdict becomes a pipeline-relevant ceiling; runs with no rails at all never count against the gate.

## v2.70.0

- the breaker inside the run: Recorder gains a live Budget — token and dollar ceilings enforced DURING recording (the `ci` gate settles after; this stops the burn). three modes: stamp (record the breach, the default), warn (stderr once per ceiling), raise (BudgetExceededError from the charging call, offending step already on the record). unpriced models never silently count as $0 — they ride in unpriced_tokens. the exit stamp lands before signing, so the signature covers the verdict.

## v2.69.0

- one mypy, everywhere: the strict bar moves into [tool.mypy] in pyproject.toml — local `mypy` and CI check the same 60 files with the same flags. configuration is code.

## v2.68.0

- the night's ledger, closed: 55 releases tonight (v2.23.0 → v2.67.0), each through the full branch → PR → 22-check CI → squash → autotag → Release pipeline. docs-only (the account itself).

## v2.67.0

- the banner's numbers age too: 34 tools / 1,500+ tests refreshed to 36 / 1,600+. banner counts get re-checked whenever a tool or test wave lands. docs-only.

## v2.66.0

- a pin should never know the version's face: the server-info pin hardcoded "2.64.0" and the very next bump flipped it red. it now asserts the real contract — SERVER_INFO == __version__ == the pyproject entry. tests-only.

## v2.65.0

- the Windows RST lesson, on the record: the test webhook answered 4xx/5xx without reading the request body, so its close sent an RST that killed the client's next retry (WinError 10053). the fake now drains the body like a real receiver. docs-only; the fix itself rode v2.64.0.

## v2.64.0

- `--version` was lying by a hundred minors: it read the installed distribution's metadata, and a stale site-packages shadowing a 2.x checkout printed 1.14.0. the version is now single-sourced from pyproject.toml — a source checkout reads the file next to the package; installed users fall back to pip's metadata. caught by the module-door pin on its first run. 2 tests.

## v2.63.0

- `python -m approximately` works: the package gained a `__main__.py`, so the module form and the console script are the same door. a RECIPES command that lied (`doctor traces --fix` — doctor only takes --store) reads --store now. 24 command families smoke-tested end to end through the module form.

## v2.62.0

- the pack verifier joins the README; distill's finite edge pinned (NaN is None, not a silent 0.0). docs+tests only.

## v2.61.0

- the reviewer's side: `evidence --verify PACK` recomputes every manifest hash and the chain inside the extracted record, printing TRUSTED or REFUSED (exit 1 refuses). the three forgery cases pinned: swapped member, rewritten record, non-pack. 4 tests.

## v2.60.0

- the README catches up: the digest drain and the offboarding archive join the capabilities table. coverage re-run confirms the night's newest code is covered. no product change.

## v2.59.0

- midnight drains itself too: the watch detects the day-file change on append and collapses the finished day to its final line right there — a watch that runs for days never needs a restart to stay drained. 1 test.

## v2.58.0

- the watch drains itself: `fleet --watch` compacts the digest history on every start — one line per prior day, the next append continuing from the compacted form. a long-lived watch never needs a manual --compact-digests again. 1 test; plus a healed CHANGELOG entry the docs-health gate caught.

## v2.57.0

- `evidence --all DIR`: the offboarding archive — one pack per trace plus an index.json naming each pack, its chain verdict, and its sha256. empty stores are a loud error. 2 tests.

## v2.54.0

- the strict bar is enforced, not remembered: CI's mypy step grows --disallow-untyped-defs, so a new unannotated function fails the build exactly the way a failing test does.

## v2.53.0

- the whole tree reads clean under strict mypy: batch eight closes cli (31 signatures), ledger, mermaid, integrity, prose, precursor, diff, recorder and calibration — 59 files, ~120 signatures across eight batches. the only remaining diagnostics are import-not-found notes for optional deps not installed in the lint environment. no behavior change.

## v2.52.0

- strict-mypy batch seven: all seven contrib adapters join the typed set — `report()` returns the FailureReport object, now stated in its type. 30 modules strict. no behavior change.

## v2.51.0

- strict-mypy batch six: report, markdown_report, importer and merge join the typed set — 23 modules strict-clean. no behavior change.

## v2.50.0

- strict-mypy batch five: mastdata, anomaly, detectors and benchgate join the typed set — 19 modules strict-clean. no behavior change.

## v2.49.0

- strict-mypy batch four: store, context and mcp_server join the typed set — 15 modules now read clean under --disallow-untyped-defs, covering the storage layer, the context runtime and the whole MCP transport. no behavior change.

## v2.48.0

- strict-mypy batch three: fleet and exporter join the typed set — 16 more signatures, 12 modules total. no behavior change.

## v2.47.0

- strict-mypy batch two: query, attributor, cluster and spool join the typed set — the analysis spine reads clean under --disallow-untyped-defs (10 modules total, 31 signatures). no behavior change.

## v2.46.0

- strict-mypy batch one: metrics, evidence, curve, align, distill and judge are fully typed under --disallow-untyped-defs (19 signatures, no behavior change). the audit's verdict: bandit clean at low severity; xenon's C bar stays as recorded debt.

## v2.45.1

- the coverage tail: the dead zero-scale heuristics removed (the mean-abs-deviation fallback made them unreachable) and the doctor's last render branches covered — forged ledgers render TAMPERED, locked chains note themselves, stale locks flag and fix. 5 tests.

## v2.45.0

- the digest drain: `fleet --compact-digests` collapses each day's snapshot history to its last line (the final state plus the snapshot count) — a 10s watch writes 8,640 lines a day and the trend reader only ever reads the day's final state. dry-run honest; the next append continues from the compacted form. fleet's store list is now optional. 8 tests.

## v2.44.0

- the threat model catches up to the night: six new SECURITY.md rows (CSV formula injection, evidence-pack hashing and its limits, zip bombs, webhook pacing, matches regex bounds, init's never-overwrite), fuzz rounds 1-19 listed. 1 test.

## v2.43.1

- the ci gate budget carries Windows headroom: 10s (from 5s) for `ci`, 8s for `evidence` — the Windows runner tripped the old budget on 10k-trace file I/O. no product code change.

## v2.43.0

- perf gates for the evidence door (2k-step pack, 5s budget) and the compare door (2k vs 2k, 8s) — suite now 18 gates. gate bug of the round: a verdict read outside its TemporaryDirectory block could never pass. no product code change.

## v2.42.0

- fuzz round 19: `compare` refuses an empty store on either side; the non-dict-meta poison trace hunted out of detectors (five reads) and integrity.verify — a hand-edited record no longer crashes attribution, verification, or the evidence pack. 5 tests.

## v2.41.0

- the MCP server runs the comparison: `compare` as a tool with the gate's exit surfaced as ok:false and prices bridged from a JSON object. 36 tools. RECIPES 21: the deploy chapter. 6 tests.

## v2.40.0

- `approximately compare`: baseline vs candidate store — runs, failures, rate, tokens, priced spend, and the regression signal that matters: a failure mode the baseline never showed. `--fail-on-new-modes` gates CI on it. 7 tests.

## v2.39.0

- the MCP server hands over the evidence: `evidence_pack` mirrors the CLI door (same manifest, loud unknown-id error, `--key-file`). 35 tools. TUTORIAL 11 closes the loop: attribute → deep-verify → pack → gate. 5 tests.

## v2.38.0

- `approximately evidence <trace> out.zip`: the complete case in one tamper-evident archive — native record with the integrity chain embedded, HTML postmortem, annotations, an on-the-spot chain verdict (--key-file for keyed chains), and a sha256 manifest a reviewer can recompute with unzip and sha256sum. 5 tests.

## v2.37.0

- the audit round: real paths, not stand-ins. the spool's real HMAC-signed webhook verified against the body for the first time (every prior test injected a stub), the watch's delivery-failure and Ctrl-C paths first-run, the markdown report's rare cards pinned. spool.py 83% → 98%. 8 tests.

## v2.36.0

- fuzz round 18, quiet: the CSV and OTLP doors survive None tasks, C1-control agent names, and non-string results; the query grammar matches unicode. the README quickstart now ends with the gate loop (init → ci). 6 tests.

## v2.35.0

- every surface speaks the same money: `status --prices` grows the est-spend line (unpriced models counted), the fleet dashboard's agents table carries the p95 column, one shared pricing helper keeps all surfaces identical. 5 tests.

## v2.34.0

- the spool pager is naturally one-shot, and now it is pinned: imported files archive out (no re-page), dry runs never count failures, unparsed files never page — a drafted cooldown was rolled back because the tests disproved the storm it guarded against. `spool --json` lines now carry trace_ids. 4 tests.

## v2.33.0

- the watch does not cry wolf. `fleet --watch --webhook` gains `--alert-cooldown`: the same reason set re-pages only after the cooldown, a growing reason set pages immediately, 0 keeps the every-cycle contract. digest snapshots still write every cycle — the cooldown gates the pager, never the record. 5 tests.

## v2.32.0

- the demo tells the whole story: measured tokens and latencies on every step, plus a fare-rules lookup so the detectors have their honest 5+ samples — the report artifacts now show the token-burn bar strip and the latency stall instead of a silence that looked like a bug.

## v2.31.2

- the docs catch up to the night: README banner at current facts, RECIPES 20 (the gate chapter: init → record → tune → enforce → hygiene), ARCHITECTURE entries for doctor --deep, scaffold.py and the ci door.

## v2.31.1

- fuzz round 17: three crash classes on the night's new surfaces. `approximately init` now refuses a hostile tree (a .gitignore that is a directory, a read-only parent) instead of tracebacking, keeping the other files coming; `store.save` survives a trace whose meta is not a dict; the query grammar's `()` parses as an empty list instead of a list containing the paren token. 11 tests.

## v2.31.0

- integration round, and a real seam: `store.save` never signed — the evidence chain only existed on the recorder exit path, so adapters and scripts saving through the store directly silently skipped it. `save(trace, stamp=True)` signs chainless traces on the way in; import/merge pass `stamp=False` because foreign evidence must not acquire our chain. and a better-than-expected find: the producer's integrity chain stays verifiable across a spool hop. 2 tests, 6 fixture updates.

## v2.30.0

- the scorecards speak percentiles; the selection prices itself. tool/agent scorecards gain nearest-rank p95 columns (latency and tokens) with matching Prometheus gauges; `query --stats --prices` prices the selection, unpriced models counted. 7 tests.

## v2.29.0

- the MCP server speaks the gate: `ci_gate` (same rows and semantics as `approximately ci`, unpriced-models-fail included) and `init_gate` (the idempotent three-file scaffold). 34 tools.

## v2.28.1

- every new door gets a tripwire: four perf gates for ci (10k traces), doctor --deep (2k chains), clean --max-traces, and csv export, budgets from local 10k measurements with runner headroom. perf-gate suite now 14 gates.

## v2.28.0

- `approximately init`: gate the repo you already have. wires a GitHub Actions workflow running `approximately ci`, a starter price table, and a .gitignore line into an existing repo — idempotent, nothing overwritten without --force, and .gitignore only ever appended to. 6 tests.

## v2.27.0

- the webhook retries like it means it. connection errors and 5xx/429 now retry with bounded exponential backoff; a 429 honors a capped Retry-After; other 4xx stay a definite answer; a fresh Request per attempt. fleet watch and spool watch both inherit the tougher delivery. 7 tests.

## v2.26.1

- no blind spots on a flat baseline. ms-rounded tool latencies make MAD == 0 common, and the modified z-score went quiet exactly where an outlier is most obvious. the scale falls back to the mean absolute deviation when MAD collapses; only a truly uniform sample stays an honest no-op. swept across all four meters (per-trace/fleet × latency/tokens). 6 tests.

## v2.26.0

- the trends you can see. fixed: the fleet trend section's failure-rate curve never rendered (it read the wrong key from the day rows). the trend section gains inline-SVG curves for slowness, token-burn and spend; a trace's token-anomaly card opens with a bar strip of every tool call's tokens — a retry loop is a skyline spike, not a footnote. 7 tests.

## v2.25.1

- CSV cells refuse to execute. `export --format csv` quotes cells beginning with `= + - @ <tab>` — the standard CSV-injection defense: a tool result starting `=` would run as a formula the moment the file opens in Excel or Sheets. `clean --max-traces 0` refused (0 would mean delete everything, which is rm -rf's job). fuzz round 16 chopped, garbage-stamped and fully-lying records all classified correctly; 8-thread write stampede loses nothing. 11 tests.

## v2.25.0

- the spreadsheet door; three new query operators. `export --format csv` writes one row per step — tokens/latency/errors pivot per tool per run without unpicking JSON, free text capped so a column cannot swallow the screen. the query DSL gains `endswith`, `matches` (a bounded regex compiled at parse time — the pattern arrives on a command line) and `in` with a list literal: `tools in ('search', 'deploy')` stops being five `or` clauses. 12 tests.

## v2.24.0

- retention by count; the doctor recomputes the chains. `clean --max-traces N` keeps a burst day from outliving its welcome — the age cap alone lets one busy afternoon accumulate a thousand records forever. `doctor --deep` recompute every record's integrity chain: a record can be parseable JSON and still lie, and only re-hashing the steps catches it. keyed records without the key at hand count as locked, not broken. the MCP doctor tool grows the same deep knob. 11 tests.

## v2.23.0

- `approximately ci`: quality gates for agent pipelines. one command composes the ceilings — failure rate, p95/avg step latency, tokens, estimated spend — into a single verdict with pipeline-native exit codes (0 pass, 1 breach, 2 configuration error or empty store). latency meters on step latency, the same ruler as the anomaly detector; spend refuses to pass unpriced models, because a budget you cannot compute does not hold. `Recorder.tool` gains first-class `latency_ms` so adapters that measured the call themselves can land real durations in the Step. 11 tests.

## v2.22.0

- the stdio flush: the MCP server answers over real pipes. a subprocess smoke of the flagship entry point found the biggest bug of the night — the serve loop wrote each response with stdout.write and never flushed, and piped stdout block-buffers, so `approximately mcp` hung against every real client (Claude Desktop, Zed, anything that pipes). Every prior test drove handle_request in-process; the transport was never exercised. cmd_mcp now flushes per response, and a real-pipe subprocess smoke (tools/list, doctor, initialize) pins the transport forever. 1 test that could only exist as a subprocess.

## v2.21.4

- Prometheus sees the tokens. `metrics --prometheus` gains `approximately_tokens_total` — the store-wide usage counter Grafana can graph and alert on (rate > 0 on an idle store = something ran; sudden jumps = a burn to investigate), covering both the text and --json doors. 1 test.

## v2.21.3

- status speaks tokens: totals and burns in the snapshot. the store health snapshot (status, --json, MCP status) carries total_tokens and the token-burn count — the last health surface that could not answer "how expensive is this store, and is anything burning". Prose gains the tokens line; 1 test.
- status speaks tokens: totals and burns in the snapshot. the store health snapshot (status --json, MCP status, watch frames) carries total_tokens and the token-burn count — the last health surface that could not answer "how expensive is this store, and is anything burning". Prose gains the tokens line; 1 test; status renderers refactored back under the C bar.

## v2.21.2

- the capabilities table tells the whole story. the README table had drifted — Log interop and Slowness rows were duplicated (an edit accident) and neither mentioned the new dialects; the duplicates are gone, interop reads OTLP/native, Slowness became "Slowness & token burn", and a Spend row joins the table — the money chain is on the front page.

## v2.21.1

- fuzz round 15: annotations on the OTLP wire. analyst-controlled strings (author, note, verdict) now cross to a tracing backend — the round-4 contract applies. Event names sanitize to [a-z0-9_.-] (a hostile verdict cannot smuggle a name), missing wall-clocks fall back to the root span's start (never epoch 0), giant notes stay capped, random annotation fuzz roundtrips idempotently. Found and hardened en route: store.annotate crashed on non-string args (a direct API call with an int verdict) — arguments are coerced. 5 tests, fixed seed.

## v2.21.0

- context audit: a nonsense budget is a loud error. the context-runtime audit (the subsystem the night had not touched) — `ContextRuntime(budget<=0)` used to be silently honored as "evict everything"; it is now a ValueError, the degenerate-behavior pin upgraded to the real contract, and the oversized-single-pin semantics (over budget and kept, because an empty context is worse) documented by the neighboring test. The rest of the audit came back clean.

## v2.20.4

- tokens in the tables people actually read. the report timeline gains a tokens column (unmetered steps show an honest dash) and the fleet card's busiest-agents table gains one too — the counts the token family runs on are visible where the traces are. 1 test.

## v2.20.3

- the spool pass counts token burns too. ingest-time signals are now symmetric — the pass report counts failure modes AND token burns among the newly imported traces (JSON field + prose "token burns: N"), so a watch line flags the expensive run without waiting for the fleet pass. 1 test.

## v2.20.2

- the sweep reaches the fixture doors. benchmark, calibrate and convert-mast join the JSON-door sweep via the shipped benchmark corpus — every --json door in the CLI is now swept with real argv, parseable output asserted.

## v2.20.1

- diff/bisect cross stores: imported vs baseline. `similar` had --other-store; diff and bisect get it — compare an imported OTLP trace against a healthy reference that lives in a different store, without merging first. The OTLP flow's postmortem question ("what diverged from the baseline?") now answers across stores. 3 tests.
- the version bump that silently no-oped. the cross-store round's sed looked for `version = "2.19.0"` while main already carried 2.20.0 — the bump matched nothing, the merge shipped at 2.20.0, and autotag correctly said "nothing to release". The lesson is now mechanical: bumps use an any-version regex and are verified with grep in the same breath. Item 253 rides this release.

## v2.20.0

- fleet --alert-spend: the budget pages too. `fleet --watch --alert-spend USD` alerts when a store's estimated spend crosses the budget — same quiet-by-default contract as the anomaly gates (a rate threshold quietens; gates add fire conditions), and unpriced stores never trip it. Symmetric with --alert-anomalies / --alert-tokens. 3 tests.

## v2.19.0

- the spend trend: rising cost is a verdict. digest rows sum each store's est_spend into a per-day series, and `fleet --trend` judges it with the same Theil-Sen machinery — a "spend trend" badge in the fleet HTML, a prose line with the $/day slope, present only when prices were in play (zeros never invent a verdict). 2 tests.

## v2.18.0

- the spool can page: spool --webhook. when a failed run actually lands in a pass, the spool watch POSTs the pass result (with the ingested failures called out) through the same HMAC-signed channel as the fleet webhook — quiet-by-default (clean passes never post), delivery failure is a stderr warning that never stops the loop, and `notify(...)` is injectable for tests. notify_webhook grows an optional payload parameter; RECIPES 18 already told this story. 2 tests.

## v2.17.0

- triage travels: annotations ride OTLP export. analyst annotations leave the store as OTLP events on the root span (`annotation.<verdict>` with author and note attributes, capped at 10) — the verdict a human reached is visible in Jaeger/Tempo next to the failure. Annotation-less traces keep their exact bytes (byte-stability pinned); the reimport path is unaffected. 2 tests; the root-span builder extracted to keep the C bar.

## v2.16.0

- markdown report parity: the anomaly cards land there too. the HTML report had latency/token cards; the markdown postmortem (the one that pastes into tickets) grew the same two sections — Latency anomalies and Token burn bullets with step, tool, amount, median, z and direction — best-effort like everything else in that renderer. 1 test pins html/markdown agreement on the same burn.

## v2.15.0

- docker: the MCP server in a container. a python:3.12-slim image — zero dependencies means the image is just Python — ENTRYPOINT approximately, CMD mcp (stdio), APPROXIMATELY_HOME defaulting to a volume-friendly /agents/store. CI grows a docker job that builds the image and asserts the container's --version matches pyproject. README quickstart shows the two commands. Found en route: the image build caught pyproject's LICENSE reference needing the file copied.

## v2.14.4

- the empty-store tour: surveyed, not invented. a new user's first command runs against an empty store — every door's actual behavior is now pinned from a survey, not assumptions: aggregate doors report zeros (doctor/stats/fleet --json), query returns an empty selection, dedupe/export/report do honest zero-work, and the needs-a-target doors (anomalies on 'latest') refuse with exit 2 "store is empty" — the typo protection, documented. 4 tests.

## v2.14.3

- agents can ask what the fleet spent. MCP `survey` gains an optional `prices` argument (JSON object model -> blended $/1k, validated) — the fleet summary an agent already reads now carries per-store `total_tokens` / `est_spend` / `spend_unpriced_tokens`. 1 test; mcp-tools.json regenerated.

## v2.14.2

- audit: verify says unsigned, and the money path stays fast. (1) semantic pin — a foreign OTLP trace has no evidence chain, and `verify` says "unsigned", never "TAMPERED" (the honest verdict an operator scanning `verify --all --json` needs). (2) perf-gate[survey-spend]: the money rollup over a 10k-trace store stays inside budget — seeding is setup, the survey itself is what's timed. Gate count: 10.

## v2.14.1

- the JSON-door sweep: every --json parses. the v221 tour generalized — every command with a --json flag driven with real argv against a seeded store; the contract is exit 0/1 plus parseable JSON. Found and fixed: `optimize --json` on a probe-less trace printed prose with the flag set — now honest JSON (`optimized: false`). `report --json` documented as --all's index manifest and swept as such. 8 doors.

## v2.14.0

- per-model token baselines: a gpt-4o and a mini are different rulers. `detect_fleet_token_anomalies(per_model=True)` splits each tool family by the trace's recorded model — pooled, a big model's honest usage cries wolf and a mini's real burn hides in the noise; split, the mini burn is the only flag and its tool name carries the model (`search [gpt-4o-mini]`). `anomalies --per-model` (with --tokens --all) and MCP `per_model` flag; default stays pooled for compatibility. 1 rewritten test tells the story.

## v2.13.1

- the trend page grows a token-burn badge. the fleet HTML trend section renders the token-burn series (badge + slope line + a table column) beside the slowness one — either series alone also renders; ANNOUNCE- MENT's 2.x era covers the money chain (v2.10-v2.13).

## v2.13.0

- the fleet sees the money. survey carries each store's total tokens, and `fleet --prices FILE` adds a per-store spend estimate (blended $/1k per trace model, unpriced tokens counted) — reaching the store card, `fleet --json`, the digest snapshots and webhooks (additive fields), and the watch loop. Bad price files exit 2. 6 tests.

## v2.12.4

- spool --json: the watch loop goes machine-readable. every pass prints one JSON line (pass number, counts, failure modes, errors) — the last prose-only command joins the --json family, so a cron spool can feed a dashboard without screen-scraping. 1 test.

## v2.12.3

- RECIPES 19: the money chapter. the three doors token data flows in through (adapters, OTLP GenAI conventions, the recorder), the two pricing modes, the budget alarm, and the honesty rules — in one recipe.

## v2.12.2

- fuzz round 14: the money entrances. the round-4 contract plus arithmetic sanity for everything that drives an alarm. Negative or absurd token counts clamp to [0, 10M] at import (a negative count poisoned every total); `_genai_tokens` reads `gen_ai.usage.total_tokens` (it only summed the splits); a negative rate in a prices table is exit-2 config error; 40 random price files and 200 random envelopes keep totals in range without crashes. Found and fixed en route: a missing tool fell back to the string "null" (_text(None)) instead of the span name. 6 tests, fixed seed.

## v2.12.1

- foreign traces know their model. OTLP import reads `gen_ai.request.model` off the root span when our own attribute is absent — so `stats --prices` prices a third-party agent's traces by their real model instead of lumping them into "unknown". 1 test.

## v2.12.0

- the budget becomes an alarm: stats --fail-over USD. with a price in play (--prices or --price-per-1k), `stats --fail-over 50` exits 1 when the estimated spend crosses $50 — cron/CI gets a spend alarm without a webhook. Without a price the flag is exit 2 with a stderr explanation, never a silent pass. An empty store prices to $0 and stays calm. 5 tests.

## v2.11.0

- models price differently: stats --prices FILE. a blended rate treats a $0.50 mini and a $15 reasoning model as the same line item. `stats --prices table.json` (model -> blended $/1k) groups tokens by the trace's recorded model and prices each bucket; models without a rate stay honestly `unpriced` — counted in unpriced_tokens, never silently free. Bad files exit 2 loudly. 5 tests.

## v2.10.1

- adapters feed the token family for real. two disconnects, one fix. (1) The LangChain/ LangGraph handler never recorded the model's completion — on_llm_start wrote a plan step and the answer (with its usage) vanished; on_llm_end/on_chat_model_end now capture text and tokens from every response shape LangChain has shipped (llm_output.token_usage, per-generation response_metadata, usage_metadata, generation_info). (2) Every adapter passed tokens= into **meta — Step.tokens stayed 0 and the token-baseline family starved on exactly the data it was built for; tokens is now a first-class recorder parameter. LlamaIndex payloads get the same usage extraction (usage dict naming eras + additional_kwargs.token_usage). 10 tests, all duck-typed, no framework installed.

## v2.10.0

- foreign agents join the token baselines. OTLP import maps the GenAI semantic conventions — `gen_ai.usage.{completion,output,prompt,input}_tokens`, any naming a backend picks — onto step tokens, and a span that metered usage becomes a tool_call step (the vocabulary token baselines measure). A third-party agent's burn is now baselined, flagged and priced straight from the OTLP it already exports. 3 tests; the CONTRIBUTING good-first-issue closes itself.

## v2.9.7

- the front doors mention the new rooms. README's step-by-step gains step 5 — circulate (OTel/OTLP export-import, the spool that feeds itself); CONTRIBUTING's good-first-issues grows the GenAI semantic-conventions mapping (map gen_ai.* attrs onto steps at OTLP import so token baselines work on traces that never touched our recorder).

## v2.9.6

- the interop matrix, pinned in one place. every export format (openai-jsonl, native, otel) under one parametrized contract — roundtrip imports load, attribute and render; each format's second-generation export is byte-stable against itself; native stays lossless (dict-for-dict); and all three dialects agree on the story (same tasks, same success flags) no matter the fidelity. 5 tests.

## v2.9.5

- the demo carries a token receipt. the 30-second tour's panic re-checks now record their token cost (800 / 850 / 9,500), so `stats --price-per-1k` on the demo store prints a real spend line — $33 at a $3/1k blended rate for one 40-second booking attempt. The token-anomaly card stays absent on purpose: 3 metered calls is under min_samples, and the demo is honest about that too.

## v2.9.4

- the perf gate watches the spool too. perf-gate[spool] — 200 mixed files (150 transcripts + 2 OTLP envelopes) through one spool_pass within budget, so the forever-running watch loop's pass stays cheap as the format surface grows. Gate count: 9.

## v2.9.3

- the money number gets a per-row breakdown. `stats --by-tool` and `--by-agent` grow an `est_cost` column (JSON + prose) when `--price-per-1k` is set — which tool, which agent, how much. 3 tests.

## v2.9.2

- the CLI tour: real argv through every wired door. per-command tests own the semantics; the tour owns the wiring — main() with actual argv lists. It caught two real bugs immediately: `approximately export` and `approximately import` read args.json unconditionally but their parsers never defined --json, so the plain commands crashed with AttributeError (per-command tests built Namespaces by hand and masked it). Flags added; a sweep proves no other command has the gap; import's prose now says "records" (an OTLP envelope holds many spans, so "transcripts" miscounted). 10 tour tests.

## v2.9.1

- the spool pass says WHAT landed. ingest-time attribution — the pass report counts primary failure modes of newly ingested failed traces (rule detectors, deterministic, no network), in the JSON result and on the watch line (`failures: FM-1.3 x2`). Best-effort: an attribution trouble yields no label, never a crash. 2 tests.

## v2.9.0

- the money number: stats --price-per-1k. "too big wastes money" gets a dollar figure — `stats --price-per-1k RATE` sums the recorded tokens and estimates spend at a blended rate, JSON and prose, honestly labelled (the recorder keeps one token count per step, no in/out split). 4 tests.

## v2.8.2

- the counts age; the pins keep them honest. the README still said 31 tools and 1,200+ tests — 32 and 1,300+ now (the era bullets, the capabilities table, the v2.0 callout). ANNOUNCEMENT gains the 2.x era: the OTel loop, token-burn detection, the spool watcher. Historical ledger entries stay as written — they were true then.

## v2.8.1

- fuzz round 13: spool + doctor under attack. the round-4 contract extended to the new ops surfaces — a garbage spool (60 files, unicode names, junk payloads) splits cleanly into archived/skipped/left with no crash; subdirectories are ignored; doctor's spool check tolerates a missing store directory; parallel OTLP ingest of the same file twice in flight collapses to one trace per envelope; the shipped tool inventory passes our own poisoning scan (pinned). 7 tests, fixed seed.

## v2.8.0

- the resource rides along: OTel deployment context in meta. OTLP import now carries the resource's attributes (service.name, deployment.environment, labels) into trace meta under attr. prefixes — a foreign service's name is context a postmortem wants. Our own resource marker is skipped on import so export→import→export stays byte-closed (pinned). TUTORIAL 10 walks the loop.

## v2.7.0

- spool ops: doctor checks it, agents can drive it. `doctor --spool DIR` reports pending files and the ones no pass could parse — they stay put by design, so they count against health (unparsed file = human attention needed). MCP grows `spool_once` (32 tools): one ingest pass on demand with delete/dry_run flags, so an agent can feed the store itself. 7 tests; mcp-tools.json regenerated.

## v2.6.2

- Windows maps a held lock to EACCES, not EEXIST. the CI race that killed a saver mid-spin: on Windows, `open` of a lock file someone still holds raises PermissionError (errno 13), not FileExistsError — the acquire loop treated it as fatal. It now means the same thing as contention: spin (bounded — a permissions problem that never clears raises after ~10s). Two regression tests pin both behaviors on every platform.

## v2.6.1

- integration round: four seams the module tests missed. walking export→import→export and spool→fleet end to end found four real bugs. (1) ns timestamps drifted in the last digit — OTLP times are now µs-quantized (time.time() precision; exact integer math below 2^53), so the loop closes byte-for-byte. (2) OTLP import dropped step tokens, tool_call results and errors — restored. (3) imported steps all carried index 0, colliding span ids on re-export — renumbered. (4) imported_from rode the wire and broke closure — exporter skips it; foreign backend attrs land in meta under attr. prefixes. 6 integration tests.

## v2.6.0

- the night watch notices token burn on its own. `fleet --watch --alert-tokens N` pages when a store carries N token-burn outliers under the same quiet-by-default contract as the latency gate (a rate threshold quietens, anomaly gates add fire conditions); the trend digest carries a token_anomalies series per day with its own Theil-Sen verdict (token-burn trend line in prose and the fleet HTML), and webhook/fleet JSON fields flow through. 7 tests; RECIPES 15/18 updated.

## v2.5.0

- spool: the directory that feeds the store. `approximately spool --dir D` watches a spool directory and ingests every transcript/OTLP file that lands — shared sniffer (native/openai/messages-list/otel), files move to done/ once parsed, unparseable files stay for a human, deterministic ids make re-delivery a no-op, --once is the cron mode with a gateable exit code (1 = a failed trace came in), --interval loops as a daemon. 10 tests; ARCHITECTURE + RECIPES 18.

## v2.4.0

- token burn reaches the surfaces people read. the per-trace HTML report grows a Token anomalies card next to the latency one (a burn step is the receipt a retry loop leaves behind), and the fleet survey carries token_anomalies + worst_token_anomaly per store — shown on the store card as a token-burn badge and the hardest-working step, and in `fleet --json`. 5 tests; latency cards untouched.

## v2.3.0

- token anomalies: the burn a retry loop leaves behind. the robust MAD ruler now meters tokens alongside latency — `anomalies --tokens` flags the step that worked too hard (a retry loop's receipt) per trace or across the fleet, with burn/frugal directions, per-tool family baselines, the same honest degenerate cases (min-samples, MAD==0, rare-tool pooled fallback), CLI prose+JSON, and an MCP `tokens` flag on the anomalies tool. Latency output shapes pinned unchanged; 13 tests; mcp-tools.json regenerated; RECIPES 17.

## v2.2.1

- fuzz round 12: the OTLP surface under attack. the importer eats untrusted envelopes now, so the round-4 contract extends to it — documented errors or clean skips, never a crash. Found and fixed: a recursion bomb (100k-deep JSON) escaped as RecursionError, now a ValueError; a 300k-attribute flood could bloat trace meta, now capped at 128 keys; a 200k-span flood became a 200k-step trace, now capped at 10k steps per trace with an honest truncated count. Envelopes shaped right but broken inside count as skips; 7 fuzz tests with a fixed seed.

## v2.2.0

- OTLP import: the OpenTelemetry loop closes. `import --format otel` takes OTLP trace documents in — compact envelopes one per line (the shape v2.1.0 writes) or a pretty-printed document (what backends export). Our own exports roundtrip idempotently via the approximately.trace.id attribute; foreign spans keep their name as message steps instead of being dropped; status codes map to success flags. Sniffing recognizes the shape; a parsed line that is not an envelope under an explicit --format otel is a loud error. 14 tests; mcp-tools.json regenerated.

## v2.1.0

- OTLP export: agent runs as OpenTelemetry spans. `export --format otel` emits an OTLP JSON ExportTraceServiceRequest — a root span per run, one span per step, deterministic sha256 ids, the per-step timeline rebuilt from latency_ms and honestly marked with an approximately.time.derived attribute. Jaeger, Tempo and Honeycomb ingest agent failures next to the rest of the stack's telemetry. CLI flag, MCP export_transcripts format, 11 tests including byte-stability, mcp-tools.json artifact regenerated.

## v2.0.0

- version discipline: 2.0, and a lean README. the 1.x line ran 100+ minors — anything that big is a major. pyproject moves to 2.0.0 and semver discipline is explicit: major for big or breaking updates, minor for features, patch for fixes. The README drops its 100+-row per-version roadmap (400+ lines with drifted "next" placeholders); release notes belong on the Releases page, which now renders this tag's CHANGELOG section as its body. The docs-health pin inverts to keep the README version-lean, and the repo description is one line instead of a feature dump.

## v1.100.3

- version claims for the typefix round. the drift-pins caught the typefix round shipping without its README row / PLAN item / version bump — this adds them. Proof the docs-health tests work: they failed the moment claims drifted.

## v1.100.1

- hotfix: the clean-test mtime race, properly. the v1.79.1 hotfix backdated created_at, but `clean` gates on file mtime — so the race resurfaced on Windows. The test now backdates the trace file's mtime directly with os.utime, which is what the store actually reads.

## v1.100

- the one-hundredth minor release. the milestone version the v1.99 round made the tooling ready for. State of the toolkit at v1.100: 31 MCP tools + resources, 7 framework adapters, the interop loop (import/export/dedupe with roundtrip-stable ids), the slowness story (per-tool and fleet baselines, slowness trend, anomaly paging, triage drafting), the judge economy (disk cache + tallies), 8 perf gates, and a docs set that fails a test when it drifts.

## v1.99

- the changelog is milestone-proof. pinned that version sorting stays numeric past v1.99 (v1.100 sorts after, tuple comparison not string order) and that wrapped titles still parse — the road to a v1.100 milestone is clear. Also recovered the PLAN item 203 label that a branch tangle had mislabeled.

## v1.98

- MCP `annotate` mirrors `from_anomalies`. triage drafts itself over MCP too — same semantics as the CLI (evidence inline, author `approximately`, verdict empty, no re-drafts). An MCP agent can start the triage queue; a human names the verdicts.

## v1.97

- `annotate --from-anomalies`. triage starts itself — the command drafts one note per top fleet anomaly (evidence inline: tool, latency, family median, z; author `approximately`; verdict left EMPTY for human review) for every trace that has no notes yet. Traces a human already touched are never re-drafted, and `--anomaly-count` caps the batch. `trace`/`note` become optional on the command (required in the single-note mode).

## v1.96

- closing sweep. artifacts regenerated (mcp-tools.json, CHANGELOG.md), the release sequence audited (v1.19→v1.95 complete with the one documented fold at v1.22), and the README's next-steps refreshed to name the real candidates. Docs-only; the round that closes the night.

## v1.95

- `status` names the worst tool. the glance names the top recidivist agent; now it names the worst tool too — the action-side twin. A tool whose trace failure rate is >= 50% (with >= 2 traces of evidence) shows in the payload (`worst_tool`) and the prose; quiet tools stay quiet. Participation, not proven causation — the payload carries the numbers, the prose stays one line.

## v1.94

- the sidecar mirror takes globs too. MCP \`import_annotations\` grows a \`glob\` parameter — every matching sidecar merges in one call, mirroring the CLI's multi-file behavior. Either path or glob selects the input; both omitted stays a tool error.

## v1.93

- docs health as a permanent test. the v1.15 link audit becomes automation — every relative Markdown link in README/docs must resolve, and the version claims that matter stay fresh: CHANGELOG's newest section, the README roadmap's newest row and the PLAN's newest item all track pyproject. The audits that used to be nightly chores now fail a test the moment docs drift.

## v1.92

- `test --json`. the regression scaffold command emits its artifact info as data — where the scaffold landed, the attributed mode, the next step — so a pipeline can wire EXECUTOR/AGENT_ENTRY and run pytest programmatically. The --json sweep now covers every developer-facing command.

## v1.91

- README's query row teaches the derived fields. the feature-table row for the query DSL now shows `max_latency` / `failed_tools` / `failed_agents` with a composed example — first-time visitors see the newest predicates where they read. Docs-only.

## v1.90

- fuzz round 11. the derived query fields (`max_latency`, `failed_tools`, `failed_agents`) survive hostile traces — untimed and negative latencies, unicode and 200-char tool names, unnamed agents, 10^11 spikes — composed predicates stay deterministic across runs, dedupe + export keep their counts on the same stores, and fleet z-scores are never NaN or infinite.

## v1.89

- the export path gets its own perf gate. `perf-gate[export]` — 500 traces as OpenAI chat JSONL in 21ms (budget 2s), with row-count and parseability assertions. Eight perf gates now cover both directions of the store's I/O plus every analytic pass.

## v1.88

- `cluster --query`. cluster the failures you care about — the shared query DSL filters before clustering (which modes keep recurring on deploy runs). Mirrored into the MCP cluster tool's existing expression parameter, so no schema change was needed.

## v1.87

- triage verdicts normalize. `Confirmed` and `confirmed` used to be two different verdicts — stored verbatim, filtered exactly, counted only in lower case. Writes normalize (strip + lower), the `--verdict` filter compares case-insensitively (so pre-normalization rows still match), and the coverage tally counts the pretty-cased idiom too.

## v1.86

- MCP `verify` gains `all`. the CLI's whole-store verify has an MCP answer as data — per-trace verdict rows plus a tally (intact/unsigned/keyed/rolled-back/...), `key_file` applying to every trace like the CLI's. `trace` becomes optional; the single-trace path is unchanged.

## v1.85

- markdown postmortems name fleet outliers too. the HTML postmortem grew a Fleet-outliers card in v1.55; the markdown issue-ready version gets the same section — an issue filed from the markdown carries the slowness evidence (step, tool, latency, family median, z) without opening the HTML. Best-effort like every card.

## v1.84

- the query tool's description teaches the derived fields. the MCP query schema now names `max_latency`, `failed_tools` and `failed_agents` with a composed example — schema-as-documentation, refreshed into docs/mcp-tools.json. An MCP client discovers the newest predicates without reading the source.

## v1.83

- `failed_agents` completes the pair. `failed_tools` (v1.82) names the tools that errored; `failed_agents` names the agents whose named tool calls errored — sorted and deduplicated so repeat offenders list once. Multi-agent night ops can now ask `failed_agents contains 'researcher' and success == false` with zero grammar changes.

## v1.82

- `failed_tools` joins the query DSL. `tools contains search` matches any run that used search; night ops want the runs where search *errored*. `failed_tools` is the derived list of tool names whose tool-call step carries an error, composing with every predicate (`failed_tools contains 'search' and success == false`). Zero grammar changes — just another derived list field. The insert initially split the field-getter if/elif chain and the memo/fuzz tests caught it immediately (`tokens` fell through to the fallback getattr) — fixed to a single chain before release.

## v1.81

- the import tally splits its skip kinds. `skipped` conflated two very different things — malformed lines (data loss) and duplicate transcripts (by design). The payload now carries `malformed` and `duplicates` separately (`skipped` stays the sum for compatibility), and the prose names both kinds.

## v1.80

- the doctor gets its own perf gate. `perf-gate[doctor]` walks 2000 traces + a judge cache in 86ms (budget 5s), with a record-count assertion — doctor has grown several passes (orphans, judge cache, ledger) and the night-watch invocation must stay bounded. Seven perf gates now cover attribution, scorecards, query, similarity, fleet baselines, ingest and store health.

## v1.79.1

- hotfix: the clean-test clock race returns. the backdate fix from the v1.52 era was lost in a later branch tangle and Windows CI failed three jobs on main. `test_clean_json` backdates the trace's created_at explicitly instead of racing `keep_days=0` against a just-written file.

## v1.79

- TUTORIAL section 9: start from existing logs. the canonical walkthrough gains the ingest loop (import directory/anomalies/report) pointing at RECIPES 14. Docs-only.

## v1.78

- fuzz round 10. the changelog generator on adversarial ledgers (versions out of physical order, blank-line storms, duplicate item numbers) — sorted, stable, every input version rendered exactly once; `max_latency` on degenerate traces (zero/negative/absurd); `export --dedupe` bounds; status payload shape on tiny stores. One real find: respond-only traces scored 0.0 similarity (no alignment tokens) so dedupe was blind to tool-less duplicates — two such runs are now duplicates exactly when task and final output agree.

## v1.77

- `report --all --json`. the index manifest as data — traces (id/task/failed/primary_mode), the index path, generated-report count. Also pinned: the query DSL's `max_latency` predicate flows through the MCP `query` tool unchanged.

## v1.76

- `max_latency` joins the query DSL. `duration` sums every step; night ops ask "which runs had a step slower than N". `max_latency > 5000` selects traces whose slowest *timed tool call* crossed the line — the fleet-anomaly story in query form, composable with every other predicate (`success == false and max_latency > 5000`).

## v1.75

- MCP tool #31 `plan_repair`. the read-only planning half of `repair` mirrors into MCP — applied/cleared/remaining/unrepairable as data, `--apply` stays deliberately CLI-only (31 tools, `tools/list` authoritative, artifact regenerated).

## v1.74

- `benchmark --json` / `convert-mast --json`. the benchmark result (multi-label path included — sample metrics, per-mode CIs) and the MAST-Data conversion stats emit as data. The `--json` sweep is now complete: every command that prints numbers also prints them as data.

## v1.73

- `export-dataset --json` / `distill --json`. both labeling exporters emit their stats dicts as data (written/labeled/skipped/modes, a `source` field naming the labeler, and the judge-cache tally when a teacher cache was in play) — the last human-only tallies in the labeling loop.

## v1.72

- `replay --json`. A/B replay verification is scriptable — `--json` emits both verdicts plus the step-level diffs as data (`ReplayDiff.to_dict`, asdict of the dataclasses), so a pipeline gates on `verdict == "diverged"` without parsing prose. Exit codes unchanged.

## v1.71

- the dashboard's trend section judges slowness. `anomaly_trend` (v1.52) now renders in the fleet dashboard's digest-history block — a slowness badge, slope and latest flagged-step count, and the per-day table grows a `slow outliers` column. One day of history keeps the old shape.

## v1.70

- the fleet dashboard shows the slow stores too. survey rows carried `fleet_anomalies` (v1.44) but the rendered dashboard only showed failure rates — a store running slow-but-successful looked perfectly healthy in the HTML. Store cards now grow a slowness section: outlier count plus the worst step (tool, latency, family median, z). Healthy stores render no section at all.

## v1.69

- doctor reads the judge cache's pulse. the judge disk cache lives outside the store, so doctor never saw it. `doctor --judge-cache DIR` (CLI and MCP #7 alike) counts entries and names unreadable ones — read-only, because a corrupt entry is already a safe miss at query time and deletion stays the operator's call. Also fixes doctor --json: the annotation fields (lines/corrupt/orphans, v1.25-v1.49) were never in `to_dict`, so --json has been silently narrower than the prose since the orphan feature shipped.

## v1.68

- `import` takes a directory. pointing the command at a directory means every `*.jsonl` inside it — the ergonomic zero-thought form of the glob. Non-transcript files are ignored by the expansion.

## v1.67

- `export --dedupe`. the sharing side learns the same trick as the distill side — `export --dedupe` (CLI + MCP `dedupe` param) drops near-duplicate traces from the export, so retries and cron double-fires never reach a colleague's attention. The payload reports what it dropped.

## v1.66

- README carries the new stories. the feature table gains the interop row (logs in / transcripts out) and the slowness-is-a-signal row (per-tool + fleet baselines, alerting) — the two headline capabilities of the v1.35-v1.65 arc finally surface where first-time visitors read. Docs-only. (Also: the ledger renumbered physically; items 164-176 sit at the tail after insert-anchor drift.)

## v1.65

- CONTRIBUTING refreshed for the community phase. the full local gate checklist (suite, lint, types, complexity, security, bench-gate, the six perf budgets), the one-version-per-PR discipline (bump, PLAN item, regenerate the pinned changelog), the --json + MCP-mirror rule for new commands (dangerous ops deliberately CLI-only), and the real CI matrix (3 OSes × 5 Pythons). The old file predated the generated changelog and the anomaly gates.

## v1.64

- ARCHITECTURE documents the anomaly family. a dedicated section for the latency signal — per-trace vs fleet baselines, the degenerate-case ladder (pooled fallback, MAD-zero sentinels), the slowness trend and its three surfaces, the alerting gates, and the perf budget. Docs-only, closing the documentation debt of the anomaly streak (v1.35-v1.60). Ledger renumbered physically (duplicate 171s from drifted insert anchors).

## v1.63

- the ingest path gets its own perf gate. `perf-gate[import]` pushes 500 mixed-shape transcripts (tool_calls, tool errors, multi-turn) through a fresh store on 4 threads — 137ms against a 2s budget, with count AND failure-flag assertions so a silent data-loss regression fails the gate, not the user's dataset.

## v1.62

- `--watch --on-change`. long watches printed the same frame every interval; `--on-change` suppresses an unchanged payload (frames still count so `--frames` still bounds the loop) and the next real change prints again — a night of logs stays one screen instead of five hundred.

## v1.60

- slowness pages too. the watch webhook fires on worsening trends and failure-rate thresholds; now `--alert-anomalies N` also fires when a store carries >= N fleet latency outliers. A store running slow-but-successful used to page nobody — the quiet kind of failure finally has a pager. Digest snapshots still land every cycle; the threshold gates the notification, never the recording.

## v1.59

- the fleet sweep names slow stores in prose. `_print_fleet` gains the anomaly count — `prod: 412 traces, failure rate 12%, 3 slow outlier(s)` — so the text sweep carries what the JSON payload already had.

## v1.58

- the judge cache without flags. `APPROXIMATELY_JUDGE_CACHE` backs every `--judge` consumer (the flag wins when given), and the MCP `attribute` tool opens `judge` + `judge_cache` — an agent stack can ask for the judge verdict and cache it in one call. Judge absence still degrades to rules-only, over MCP too.

## v1.57

- robustness: capped dedupe scans, streamed stdin. `duplicate_groups` reports `scanned` and `capped` (CLI notes the cap, MCP payload carries both) instead of silently ignoring everything past `--max-traces`; and `import -` now streams stdin in a single pass — the sniffed first line is re-joined to the iterator, so a multi-gigabyte dump never materializes in memory. Lists still re-iterate unchanged.

## v1.56

- slowness trend parity. one `summarize_trend`, three surfaces — `fleet --trend` prints a `slowness trend:` line (verdict + slope + flagged-step count), the MCP `trend` payload carries `anomaly_trend` verbatim, and the status prose mentions it. Pinned by tests on all three.

## v1.55

- postmortems name fleet outliers. the per-trace latency card only knows what one run considered normal; the postmortem now gains a "Fleet outliers" card when a store is given — steps that are extreme against every stored run of the same tool. A trace can look normal alone and still be the slowest search the store has ever seen. Best-effort like every card: no store, no card.

## v1.54

- `approximately changelog`. the PLAN milestone ledger is the single source of truth; the new command renders it as a standard changelog — sorted by version (newest first), one section per version, early multi-item versions merged. The committed CHANGELOG.md is pinned against a fresh render, so it cannot drift from the plan. Also fixes the ledger's own ordering: item 157 sat physically after 163.

## v1.53

- MCP tool #30 `import_annotations`. the v1.50 handoff pair completes its mirror — an MCP client merges an annotation sidecar into the store (append-only, content-keyed) rather than just the transcript half. Missing file is a tool error, never a protocol fault. 30 tools, `tools/list` authoritative, artifact regenerated.

## v1.52

- slowness gets a trend. digest snapshots already carry each store's fleet-anomaly count (v1.44's webhook fields flow through), so `trend.anomaly_trend` judges slowness over days once two days of history exist (verdict + slope + latest count); the status prose prints `slowness trend: ...` when present. Also restores the status tail lines (trend/ledger/recidivist/last-failure-none) that the shared renderer silently dropped in v1.42 — a round-25 consolidation left the renderer a subset of the one-shot.

## v1.51

- the glance can fail a pipeline. cron wrappers need exit codes, not prose. `status --fail-on-anomalies` exits 1 when fleet latency outliers exist; `--fail-on-worsening` exits 1 when the trend verdict is worsening (needs `--digest-dir`). The frame still prints first — the alert explains itself.

## v1.50

- store handoff: the triage story travels. `export --with-annotations` writes the triage sidecar next to the transcript export (OUT.annotations.jsonl); `import --annotations` merges a sidecar append-only. Identity is the stable triage content (trace_id, note, author, verdict) — timestamps differ between stores, so a full re-import of the same file skips instead of duplicating. Malformed rows are counted; the evidence chain is untouched.

## v1.49

- triage coverage in the glance. `status` answered "how many failures"; now it answers "how many has anyone actually looked at" — `triage_coverage` (annotated failures over total failures) in the payload, and a prose line whenever the ratio is below 100%. No failures on file is `None`, not a fake 100%.

## v1.48

- floors that keep up. `bench-gate --update-floors` regenerates the floors file from a measured run at measured-minus-margin (default 5%) — after an intentional improvement or a corpus change, floors stop being stale. `min_records` survives regeneration unless explicitly set, and the regenerated file is verified to still PASS a fresh gate (headroom for noise, not a pass-everything gate).

## v1.47

- RECIPES: night watch and dedupe. recipe 15 ties the night story together (`status --watch` + fleet baselines + the multi-project sweep, with a note on reading modified z-scores); recipe 16 walks dedupe before a fine-tuning export, with the teacher cache tally. Docs-only. ## 4. Launch plan 1. **Artifacts**: public GitHub repo + PyPI + technical blog post (MAST-data visualization, demo GIF). 2. **Channels in order**: ① Hacker News "Show HN: Approximately – a dashcam and automatic postmortems for AI agents"; ② r/LocalLLaMA + r/LLMDevs (local-model judge angle); ③ X/Twitter agent community; ④ Chinese dev communities (Jike/Zhihu). 3. **Above-the-fold promise**: `pip install approximately && approximately demo` → a full attribution report in 30 seconds. 4. **Virality hook**: every HTML report footer carries the repo link. 5. **Metrics**: 500 stars / 2k PyPI downloads in month one = healthy; the core conversion is demo → own-agent instrumentation, so the Recorder API must stay ≤ 5 lines. ## 5. Risks & mitigations | Risk | Mitigation | |---|---| | Langfuse/LangSmith build attribution downstream | they are SaaS-tracing-first; we are local, zero-dependency, MAST-semantic; open-source speed is the moat | | Rule-detector false positives | every Detection carries readable evidence; rule vs judge sources are labeled separately; confidence thresholds configurable | | Benchmark dataset licensing/reproduction | cite the taxonomy with attribution; no redistribution of MAST-Data — provide loaders, not data | | Single-maintainer bandwidth | zero-dependency core with three small interfaces (Recorder/Attributor/Replayer) keeps the maintenance surface deliberately tiny | ## 6. References Cemri et al., *Why Do Multi-Agent LLM Systems Fail?* (MAST), arXiv:2503.13657, 2025. Bohnet et al., *Why Do LLM Agents Fail and How Can They Learn From Failures?*, arXiv:2509.25370, 2025. *Who&When: Automated Failure Attribution in Multi-Agent Systems*, arXiv:2505.00212, 2025. Xie et al., *OSWorld: Benchmarking Multimodal Agents*, arXiv:2404.07972, 2024. *Efficient Context Engineering for Long-Horizon Tool-Using Agents*, arXiv:2606.10209, 2026. Anthropic, *Effective Context Engineering for AI Agents*, 2025.

## v1.46

- the distill pipeline learns to dedupe. `export-dataset --dedupe` and `distill --dedupe` drop near-duplicate traces before labeling — retries and cron double-fires otherwise get labeled, exported and trained on as if they were independent evidence. The pass prints what it dropped; without the flag nothing changes.

## v1.45

- dedupe: near-duplicate traces. `import` deduplicates exactly (deterministic ids); `dedupe` catches the *almost* identical runs — retries and cron double-fires that quietly pollute a dataset before a fine-tuning export. Single-pass clustering against representatives keeps it O(n·k) (not O(n²)); id-ordered scan makes groups reproducible; MCP tool #29 `find_duplicates` mirrors it (29 tools, `tools/list` authoritative, artifact regenerated).

## v1.44

- the fleet sweep counts slow spots. `fleet` survey rows (and the MCP `survey` mirror and every webhook payload) carry `fleet_anomalies` — the store-wide per-tool outlier count — plus the worst offender, so a multi-project sweep answers "which store is quietly slow" without visiting each one.

## v1.43

- the fleet scan gets its own perf gate. every analytic path earns a budget; `perf-gate[fleet-anomalies]` baselines 10k traces x 2 tools (crafted spikes included, and the gate fails if the crafted outliers are NOT found — a silent no-scan passes nothing) in 6ms against a 2s budget. Guards the night-watch `status` frame against a superlinear baseline regression.

## v1.42

- the ops glance knows the fleet. `status` (CLI and MCP #28 alike — they share `_status_payload`) now carries `fleet_anomalies`: the count of store-wide per-tool latency outliers and the worst offender (tool, latency, family median, z). The prose render names it when nonzero, and the one-shot/watch/JSON modes now share ONE renderer, so the glance cannot drift between modes.

## v1.41

- fleet-mode latency anomalies. a per-trace baseline only knows what one run considered normal. `detect_fleet_anomalies` (CLI `anomalies --all`, MCP `anomalies` with `fleet: true`) baselines each tool family across every trace in the store, so a single 30s search inside an otherwise boring week stands out even though that trace, alone, looks unremarkable. Families under `min_samples` are honest no-ops; findings carry their `trace_id`.

## v1.40

- parallel ingest. `import --jobs N` imports files on a thread pool — store saves are atomic and lock-serialized, so the parallel path is safe, and aggregate + per-file counts stay in input order whatever the completion order was. One bad file no longer kills a batch: multi-file runs record a per-file `error` and an `errors` count and keep going, while a single named file that cannot be parsed stays a loud exit-2. Identical transcripts arriving in flight collapse to one trace (same deterministic id).

## v1.39

- the cache shows its work. `judge.cache_stats()` counts hits and misses since process start (reset on read), and `export-dataset --teacher-cache` prints the tally after a run — a cold dataset reads `0 hit(s), N miss(es)`, the same dataset relabeled reads `N hit(s), 0 miss(es)`. Seeing is believing for the money-saving claim.

## v1.38

- the tool inventory as an artifact. `approximately mcp --print-tools [PATH]` writes the exact `tools/list` inventory as JSON (stdout with `-`). The committed docs/mcp-tools.json mirrors it and a test pins the file against `_TOOLS`, so docs can cite the whole surface — descriptions, schemas, count — without ever drifting from the code.

## v1.37

- safer store maintenance. `clean --dry-run` rehearses a retention policy without touching a file (JSON payload notes the dry run), and `rotate --all` re-keys every trace in one pass — the quarterly key-rotation story — listing refusals per trace and exiting 1 if any evidence was already broken (the per-trace `rotate` still verifies with the old key before re-signing).

## v1.36

- fuzz round 8: the cache and the baselines. the fuzz tradition reaches the v1.27-v1.35 surfaces, and every finding was real. The judge cache now shape-validates what it serves (poison that `_parse_verdict` would coerce — numeric mode_ids, dict rationales, string confidence — is a miss, not a corrupted hit); the rare-tool fallback names the MAD==0 case (">50% identical steps leave no scale") and flags a rare call that differs from the median at all; `status --watch` clamps negative intervals; `scan-tool --text` gives the CLI the inline path the MCP tool already had.

## v1.35

- per-tool latency baselines. `detect_latency_anomalies(per_tool=True)` baselines each tool family separately (CLI `anomalies --per-tool`, MCP `per_tool`). Pooling a 2s-search trace with 30s deploys builds one scale where neither family's spikes stand out; per-tool medians catch the 3x deploy immediately. Families smaller than `min_samples` fall back to the pooled scale — their own latencies judged against the whole-trace median/MAD — instead of going blind on rare tools. Identical-latency families are honest no-ops.

## v1.34

- MCP tool #28 `status`. the ops pair completes its mirror — `annotate` mirrored long ago, now `status` returns the same one-glance payload over MCP (store health, top modes, triage tallies, last failure + chain verdict, ledger health, top recidivist, optional fleet trend via `digest_dir`, `since` window). A night-watch agent or dashboard reads exactly what the operator sees; the payload is the shared `_status_payload`, so CLI and MCP cannot drift.

## v1.33

- the distill loop learns to remember. `teacher_labeler` takes `cache_dir` and both teacher consumers grow `--teacher-cache DIR` (`export-dataset`, `export-sft`) — relabeling a dataset is free for every trace asked before; `benchmark --judge-cache` already had it. Low-confidence and OTHER verdicts still label None; a JudgeError still labels None; the cache only removes the repeat cost.

## v1.32

- precision knobs. `similar --min-score` cuts weak neighbours instead of always returning a full top-N (CLI and MCP `min_score` alike — the cap still applies on top), and `import_transcripts` grows a `glob` parameter so an MCP client pulls a whole directory of dumps with the same aggregate + per-file counts the CLI prints. Similarity caps and floors compose: top-N picks, then the floor filters.

## v1.31

- export --since + the toolscan mirror. `export --since DAYS` puts list_traces' age window on the export path (CLI and MCP `export_transcripts`), so yesterday's failures go to a colleague without the whole store. The toolscan finally mirrors into MCP per the ops-pair rule — tool #27 `scan_tool` takes a file path or the description inline and returns verdict + findings; a missing file or missing input is a tool error, never a protocol fault.

## v1.30

- ARCHITECTURE documents the interop pair. a dedicated section for importer.py / exporter.py (shapes, deterministic ids, id-ordered byte-stable exports, the MCP mirrors), the judge disk cache, and the stats.json resource; the cli.py entry now mentions `status --watch` and that ops commands take `--json` too. Docs-only round closing the documentation debt the v1.19-v1.29 feature streak accrued.

## v1.29

- `status --watch`. the overview that stays up all night. `--watch` re-renders the status frame on an interval (`--interval SECONDS`, default 30) with a timestamp header per frame; `--frames N` bounds the loop for tests and cron wrappers; Ctrl-C exits clean. The frame renderer is shared with the one-shot mode (`_render_status`), so prose and `--json` frames stay byte-identical between the two modes.

## v1.28

- the ops seven learn --json. the all-commands-`--json` rule (v1.18) was aspirational on seven operators' commands; annotate, anomalies, metrics, clean, repair, rotate and scan-tool now all emit machine-readable payloads (`annotate` → the stored entry + note count, `anomalies` → per-step robust-z rows with direction, `metrics` → the stats snapshot or `{"format": "prometheus", "text"}`, `clean` → removed/keep_days, `repair` → applied/cleared/ remaining/unrepairable, `rotate` → rotated+trace_id or refusal, `scan-tool` → verdict+findings). Prose stays the default.

## v1.27

- the judge learns to remember. judge verdicts are disk-cacheable (`--judge-cache DIR` on attribute / report / annotate-style consumers, `cache_dir=` on `judge_trace`). The key is sha256(model, preset, compact trace) — the same failure asked twice skips the API call entirely, and a hit is indistinguishable from a fresh answer. Different model or preset re-asks; corrupt entries are misses; a read-only or full cache never fails the judge; a JudgeError is never cached. Real money saved on the attribute→benchmark→distill loop.

## v1.26

- `import -` reads stdin. piping is the agent-native ingest path — `other_tool dump | approximately import - --store s` lands runs in the store without a temp file. `-` mixes freely with file and glob arguments (per-file counts list `<stdin>`); empty stdin is a documented ValueError. The line loop is shared by files and streams (`import_lines`), so sniffing, idempotence and skip-counting behave identically. RECIPES gains recipe 14: bring last month's logs in for a postmortem.

## v1.25

- doctor finds orphan annotations. after an import/clean/rotate cycle the annotation sidecar can reference traces that no longer exist. Doctor names them (count in the annotations line, up to five ids listed) so triage knows which notes point at nothing — read-only diagnosis; `doctor --fix` still only removes locks and temp files, never notes.

## v1.24

- MCP stats resource. the resource surface grows `approximately://{store}/stats.json` — store health (trace count, failure rate, top failure modes) readable by any MCP client without calling a tool, next to the annotations sidecar and per-trace entries. Dashboards get a browse path that stays out of the tool budget.

## v1.23

- import at scale. `approximately import` takes several file arguments and expands glob patterns (sorted, deduplicated); the JSON payload aggregates lines / imported / skipped across files with a per-file breakdown. Deterministic ids now dedupe across files: the same transcript in two log files is one trace. No match is a documented ValueError (CLI exit 2), not a silent success.

## v1.22

- fuzz round 7: the interop surface. the fuzz tradition reaches the import/export pair. Properties, 40 seeded random traces (messages, tools with hostile args/results, plans, error steps, unicode tricks): export→import restores id/task/success and the second export is byte-identical; hostile lines on either direction are counted skips or documented ValueErrors, never crashes; 60 random hostile message dicts always produce consistently-indexed steps; the MCP mirrors roundtrip 10 traces with dry-run idempotence. Two real finds fixed: assistant messages with empty content were dropped on import (breaking the export fixpoint), and explicit-null success now roundtrips as an open trace instead of flipping to closed.

## v1.21

- export: the path out. `approximately export OUT.jsonl` writes traces in the dialect other pipelines speak — OpenAI chat shape by default (adjacent tool_call steps merge into one assistant message; observations pair with call ids in order; a call whose recorder kept result/error with no observation rides its own tool message with `is_error`), `--format native` for the lossless chain-verifying dump. Our exports carry `metadata.task` / `metadata.trace_id`, and the importer reads them back, so export→import restores ids and re-importing an export is idempotent. `--query` filters with the shared DSL (`success == false`). Mirrored as MCP tool #26 `export_transcripts` (missing output directory → tool error, never a protocol fault).

## v1.20

- MCP tool #25 import_transcripts. the import path mirrors into the MCP surface per the ops-pair rule — an MCP client points at a foreign transcript JSONL and pulls it into the tamper-evident store with the same sniffing, sha256 idempotence and dry-run semantics as the CLI. A missing file is a tool error (`isError: true`), never a protocol fault. The authoritative tool list stays `tools/list`; the pinned count test moved to 25.

## v1.19

- import foreign transcripts. the contrib adapters transcribe live frameworks; `approximately import` is the path in for logs already on disk. One JSONL file, one transcript per line, three shapes sniffed from the first line: native `Trace` dumps, OpenAI chat dumps (`messages`, tool `is_error` becomes a failed step and a failed trace), bare message arrays. Foreign lines get deterministic sha256 ids, so re-importing the same file skips everything instead of duplicating. Malformed lines are counted, never fatal; `--dry-run` previews counts without writing; `--json` for scripts.

## v1.18

- ARCHITECTURE CLI entry. the module map documents the ops pair (`status`, `annotate` / `annotations --verdict`) and the all-commands-`--json` + MCP-mirror rule. Docs-only.

## v1.17

- status --since scopes annotations. the --since window now filters triage tallies along with traces - the counts must describe the same period as the runs they talk about. 1 new test.

## v1.16

- MCP annotate lists the whole store. calling the annotate tool with neither trace nor note returns every annotation in the store; the trace field drops from required. Completes the triage read path for fleet-wide views. 1 new test.

## v1.15

- link audit + leaderboard artifact. the docs link audit found the README pointing at two leaderboard HTMLs that were never generated. make_docs_artifacts.py now renders leaderboard.html alongside the other four pages, and the multi-label link points at the doc page that exists. Broken-link check stays a manual audit step (zero-dep tooling).

## v1.14

- final night audit. closing sweep for the 51-round session - version surfaces re-verified (pyproject / package / MCP handshake all read the installed distribution), 24 unique MCP tool names, PLAN as a continuous 1-124 ledger, README roadmap aligned. All gates green; releases v0.63.0 through v1.14.0 every round, each Latest-sequenced.

## v1.13

- status knows the ledger and the top recidivist. the ops overview now also reports evidence-ledger health (intact / BROKEN when the ledger is in use) and the busiest recidivist agent via the min_failed=2 filter - JSON fields plus text lines. 1 new test surface via the existing status fixtures.

## v1.12

- PLAN renumbered. the milestone ledger itself got an audit - items 54-56 and 80 had drifted into the appendix zone through the years of anchor-based inserts; the delivered list now reads as one continuous 1-121 sequence. Docs-only.

## v1.11

- bench-gate min_records. floors guard quality, but nothing guarded *sample size* - a dataset that shrank could pass any floor by luck. floors JSON gains `min_records`: below it the gate fails with a violation that names the shrinkage. 1 new test.

## v1.10

- MCP explain/annotate final parity. the MCP `explain` tool returns the full payload (fixes + the watching detectors from the live registries) matching the CLI's `--json`, and the `annotate` read path gains a verdict filter. 2 new tests.

## v1.9

- fresh-install CI job. a clean-venv, non-editable install job - the version handshake must match the checkout, the demo tour must run, and a record -> attribute -> status loop must work through the installed console script with a default home. Catches packaging breaks (missing data, wrong entry points, drifted metadata) that editable installs hide.

## v1.8

- explain --json full depth + annotate verdict filter. `explain <mode> --json` carries the mode's fixes and its watching detectors (from the live registries, not docs); `annotations --verdict confirmed` filters the triage log. 2 new tests.

## v1.7

- per-tool Prometheus metrics. `metrics --prometheus --by-tool` and MCP `metrics {group_by: "tool"}` render tool_scorecard rows as approximately_tool_* series - the renderer is generalized so agent and tool share one implementation. 1 new test.

## v1.6

- nearest neighbours on the postmortem. the report answers "which runs look like this one" - an alignment-ranked table of the three most similar runs in the same store, on both HTML and Markdown, hidden when the store is empty or the trace is alone. Same-store only by design: cross-store stays an explicit `--other-store` question. 3 new tests.

## v1.5

- similar perf gate + cross-store recipe. the fourth perf gate pins rank_similar's pruning - a 2000-trace ranking must stay in budget (0.2 s against 2 s) or the pruning has regressed. RECIPES' neighbour recipe gains the cross-store form. No library changes.

## v1.4

- rank_similar pruning. similar's ranking normalized the target's tokens once per candidate and ran the quadratic DP for every one. Now the target normalizes once, and a candidate whose length-ratio upper bound (similarity <= 2*min/max) sits strictly below the current Nth-best score skips its DP - provably unable to enter the top N, so the ranking is byte-identical (ids and scores pinned against a brute-force reference). 2000-trace store: 0.20 s. 2 new tests.

## v1.3

- the operator journey, end to end. one subprocess-driven test walks the whole story through the real CLI - record, attribute, report (HTML+Markdown), cluster, mint a regression guard, annotate, status, verify --all, fleet survey + digest + trend. Each hand-off is a seam a regression would break; now they are all watched. 1 new test (the longest in the suite).

## v1.2

- TUTORIAL: the triage step. the ten-minute walkthrough gains step 6 - annotate the human verdict onto the machine one, then read `status` for the pulse. Fleet watch shifts to 7, quality floors to 8. No code changes.

## v1.1

- status --digest-dir. the first post-1.0 minor. `status --digest-dir DIR` folds the fleet trend verdict into the ops overview - text line (`fleet trend: stable`) and a `trend` object in JSON - so the daily glance and the monitoring history finally live in one command. No breaking changes (1.x contract). 1 new test.

## v1.0

- the 1.0 milestone. semver from here. The toolkit ships 24 MCP tools + a resources surface, 7 framework adapters, MAST attribution gated by a quality floor (gold + synthetic corpora), tamper-evident chains with annotation sidecars, fleet monitoring with quiet-by-default alerting, regression-test minting, and 1,000+ tests across a 15-job CI matrix covering 6 Python lines on 3 operating systems, with bandit + secret scanning and SHA-pinned actions. 1.0 means: the public API (Recorder, TraceStore, attribution, query DSL, MCP surface) is stable; breaking changes require a 2.0.

## v0.99

- the --json sweep completes. the last four prose-only commands learn machine: `optimize --json` (minimal budget + recall), `calibrate --json` (split, temperature, coverage vs target, ECE), `explain --json` (one mode or the full table), `taxonomy --json` (the whole MAST table with definitions). Every analysis/reference command in the CLI now has a structured output path. 3 new tests.

## v0.98

- RECIPES smoke. the cookbook's walkthrough (RECIPES 3-4) now runs in CI - attribute --explain, explain <mode>, bisect, the minted regression guard collected by pytest, verify and status. When a recipe drifts from the code, the failure names the exact line. Signed-store fixtures match the cookbook context. 3 new tests.

## v0.97

- cross-store similar. `similar --other-store DIR` (and the MCP tool's `other_store`) compares a run against a different store's traces - fleet operators can ask "does THIS failure look like anything in the other project?" without merging stores first. 1 new test.

## v0.96

- fleet triage counts. the fleet surface knows each store's annotation activity. StoreSummary gains `annotations` / `annotations_confirmed`; the webhook payload, digest snapshots and the dashboard store cards carry them - "notes: 5 (2 confirmed)" sits next to the ledger state, so an operator sees triage activity without opening each store. 1 new test.

## v0.95

- `approximately status`. the daily-driver ops overview one command used to require five. Totals and failure rate, top failure modes, triage tallies (annotations and confirmed count), and the most recent failing trace with its evidence-chain verdict. `--json` for dashboards, `--since` scopes the window, empty stores render honestly (zeros, no last failure). 3 new tests.

## v0.94

- toolscan self-test + adapter map sync. the toolkit's own MCP-tool-description scanner (homoglyphs, bidi, injection) now runs against all 23 shipped tools in CI - a tool description can never ship with the pattern toolscan exists to catch. Schema shape pinned too (object type, required-keys present). ARCHITECTURE's contrib entry lists all seven adapters and the two capture styles. 3 new tests.

## v0.93

- attribution 7x faster, zero verdict drift. profiling showed the prose detectors spending 43s per 135 records inside difflib's quadratic ratio() scan. ProseRepeat and ProseRestart now gate ratio() behind its own cheap upper bounds (the 2*min/max length bound plus real_quick_ratio and quick_ratio) - pure pruning, no verdict changes: 445 -> 64 ms/record. The gate earned its keep the same night: the first pruning attempt silently dropped the restart detector's jaccard paraphrase branch and bench-gate caught the F1 dip (0.46 -> 0.43) before it shipped; the fall-through was restored and a 30-trial brute-force equivalence test now pins pruned-vs-brute agreement.

## v0.92

- docs: count-proof tool inventories. an audit caught three docs restating the MCP tool total (19/Nineteen/24 across README/ARCHITECTURE/RECIPES/TUTORIAL) - every round was drifting them. Docs now describe the inventory by concern groups without totals and point at `tools/list` (and the count-pinning test) as the authority. ARCHITECTURE and RECIPES lists also gained the recently shipped tools (anomalies, diff, regression_test, metrics, annotate). No code changes; the next tool needs no doc-count edits.

## v0.91

- MCP metrics (tool #24). store health as Prometheus text exposition over stdio - runs total, failures, failure rate, step means, per-mode counts; per-agent rates with `group_by: "agent"` (the same rendering as `metrics --prometheus`). An agent or ops scrape can read fleet health without shelling out. 3 new tests; tool count 24.

## v0.90

- MCP regression_test (tool #23). the "guard it forever" promise becomes a tool call. An agent that just failed can mint its own self-contained pytest file - the trace rides along as base64, budget and fact-recall guards configurable - and commit it where its tests live. The failure can never silently return. 4 new tests; tool count 23.

## v0.89

- MCP anomalies + diff (tools #21 and #22). `anomalies` flags per-step latency outliers (modified z-score over tool-call steps, worst first, isError on detection); `diff` gives the structural alignment of two traces with divergences ranked most-different first. The MCP surface now covers the fleet-ops and forensics pair completely. 4 new tests.

## v0.88

- CI covers every Python it claims. an audit found classifiers promising 3.10 and 3.11 while the CI matrix tested only 3.9/3.12/3.14 - two advertised interpreter lines were never verified. The matrix now runs all six combinations of {ubuntu, macos, windows} x {3.9, 3.10, 3.11, 3.12, 3.14} minus the two documented excludes. No source changes; the suite passes on every added interpreter.

## v0.87

- fuzz round 6. the resources surface and its friends under garbage - scoreboard.group_by (wrong enum values, NUL, nested lists), resources/read (truncated URIs, foreign stores, empty/NUL schemes), the watch alert threshold (negative/overshoot rates), and merge's sidecar carry (garbage lines flowing through all three conflict policies). Every probe contained. 4 new tests; corpus pinned.

## v0.86

- MCP resources + one version to rule them all. the MCP server grows a resources surface - `resources/list` exposes every trace plus the annotation sidecar as browsable resources, `resources/read` returns a trace's JSON or the notes NDJSON, and `initialize` advertises the capability. Unsupported schemes and unknown traces are -32602 parameter errors. Also: `approximately --version` had drifted to a hardcoded 0.59.0 - `__version__` now reads the installed distribution (the same source the MCP handshake uses), so all three version surfaces can never disagree again. 6 new tests.

## v0.85

- bench-gate --json, merge --json. the last CI-facing prose-only commands join the machine-readable story. `bench-gate --json` emits the structured gate result (records/modes/sample_f1/violations, exit 1 on any violation); `merge --json` emits the merge report including the annotation sidecar count. Text output unchanged. 4 new tests.

## v0.84

- counterfactual root-cause card in the reports. the strongest causal language in the toolkit joins the postmortem. HTML reports gain a "Root cause (counterfactual)" card and Markdown a matching section - which step's removal eliminates the mode, or the honest distributed-causes verdict. Affordance-gated: traces over 200 steps skip the card (the leave-one-out render stays linear; the standalone `counterfactual` surface remains for those). 4 new tests.

## v0.83

- per-tool rollup. the action-side twin of the agent scorecard. `cluster.tool_scorecard` rolls steps, touched traces, errors and touched-trace failure rate per tool; `stats --by-tool` and MCP `scoreboard {group_by: "tool"}` surface it. Same honesty contract as the agent card: participation, not proven causation. 4 new tests.

## v0.82

- docs: 20-tool inventory + quiet-alerting recipe. RECIPES' MCP inventory says twenty and names `annotate`; new recipe 13 walks the quiet-by-default watch - digest history every cycle, webhook only on signal, cron-batch arithmetic, and the survival doctrine (a dead endpoint or a torn digest line must never stop the watch). No code changes.

## v0.81

- quiet-by-default watch alerting. `--alert-worse-than RATE` gates the watch webhook on signal, not schedule - the POST fires only when a store's trend is worsening or its failure rate is at/above the line, so a healthy fleet pages nobody. Digest snapshots still land every cycle regardless: the threshold gates the notification, never the recording. 5 new tests.

## v0.80

- context/curve --json parity. the budget-pressure commands join the machine-readable story. Payload construction moves into the library (context.forecast_payload, curve.curve_payload) and the CLI (`context --json`, `curve --json` - which no longer writes the HTML page) and the MCP tools (#18/#19) render the identical object. 2 new parity tests pin CLI==MCP byte-for-byte.

## v0.79

- annotations hygiene: merge carries the sidecar, doctor reads it. notes about a run belong to the run. `merge` now transports the annotation sidecar to the target store - re-anchored to renamed trace ids, deduped on semantic identity (trace/author/verdict/note; the wall-clock ts is noise), append order preserved. `doctor` reports the sidecar's line and unreadable-line tallies; a torn tail is advisory and does not flip `healthy` (notes are triage, not evidence). 6 new tests.

## v0.78

- fleet watch webhook. `--webhook` used to apply only to one-shot surveys; the watch loop ignored it. Now every digest cycle also POSTs the same HMAC-signed fleet summary, and delivery failure is a stderr warning - never a stopped watch, because an ops loop must survive its notification endpoint being down (that is exactly when it needs to keep watching). The poster is injectable so tests run on a fake; the URL never leaks into logs. 4 new tests.

## v0.77

- bench-gate JUnit export. CI test reporters render the gate natively. `run_gate` gains `junit_path` (CLI `bench-gate --junit PATH`, script `--junit`): one testcase per guarded floor - sample_f1 plus each mode's P/R/F1 - with the floor comparison as the case name and a violation as a JUnit failure whose message carries actual vs floor. A mode the detector stops finding fails its floors loudly (missing scores never pass). 5 new tests.

## v0.76

- fuzz round 5. tonight's surfaces under garbage - the query DSL's new tools/errors fields (hostile expressions incl. unicode tool names and unknown-set literals), the four shared payload constructors (similarity tops, PSI windows, precursor probabilities over degenerate stores), the annotations sidecar (truncated lines, wrong shapes, wrong types, writes surviving garbage), and the annotate tool. Every probe contained; corpus pinned as a regression gate. 4 new tests.

## v0.75

- analyst annotations (MCP tool #20). the triage loop closes. `annotate` attaches analyst notes to a trace WITHOUT touching the trace file - notes live in an append-only `annotations.jsonl` sidecar, so the tamper-evident chain stays intact and the notes themselves are an audit log (never edited or removed, only superseded; corrupt lines from a partial write are skipped, not fatal). Surfaces: library (store.annotate / store.annotations), CLI `annotate` / `annotations [--json]`, MCP tool #20 (write with a note, read without), and both report renderers show the notes when a store is handed in (hidden otherwise - render stays a pure function). `confirmed` / `false-positive` are the documented triage verdicts. 6 new tests.

## v0.74

- CLI --json parity: similar / drift / counterfactual / predict. the MCP tools returned structured data while the CLI only printed prose. Payload construction now lives in the library modules (align.similar_payload, drift.report_payload, counterfactual.report_payload, precursor.score_payload) and both surfaces render THE SAME object - a CI job can shell the CLI and parse the identical JSON an MCP client sees. 4 new tests pin byte-level CLI==MCP.

## v0.73

- verify exit-code ladder at CLI level. all six documented verdicts pinned through the real command - 0 intact, 1 TAMPERED (rewritten step), 2 unsigned, 3 KEYED (keyed trace, no key), 4 ROLLED-BACK (ledger audit), 5 LEDGER-BROKEN (chain localized) - plus rotate's required-new-key refusal and success path. cli.py 91% -> 93%.
- query DSL: tools and errors fields. two action-side fields join the grammar. ``tools`` is the set of tool names a run invoked (``tools contains 'deploy'`` asks "did this run ever touch deploy?") and ``errors`` counts steps that errored (``errors >= 1``). Same eval-free parser, same depth/length caps; ``contains`` already speaks set membership via the agents precedent. 2 new tests.

## v0.72

- Google ADK adapter. the seventh framework adapter. A google-adk run is a list of Events; ``trace_from_adk_events`` transcribes that history (function_call -> tool call, function_response -> tool result with usage_metadata token counts, text -> plan from the user side / response from the agent side, last agent text becomes final_output) with zero imports from the framework - duck-typing on part attributes, control events (yield/transfer/auth) with no content skipped. ``record_adk_events`` is the one-liner. 5 new tests on fakes; the contrib CI job covers the real package.

## v0.71

- pydantic-ai adapter. the sixth framework adapter. Pydantic AI runs end with ``result.all_messages()``; ``trace_from_pydantic_ai`` transcribes that history into an approximately trace (UserPromptPart -> plan, ToolCallPart -> tool call, ToolReturnPart -> tool result with per-message token usage, TextPart -> response), reading both Usage naming eras. Pure duck-typing on part class names - zero imports from the framework, so the core stays dependency-free and the tests run on fakes; the contrib CI job covers the real package. ``record_pydantic_result`` is the one-liner for the common case. 6 new tests.

## v0.70

- packaging demo smoke. the packaging job's clean-venv smoke now also runs both multi-agent demo scenarios through the installed wheel and greps for the expected detector sources - the wheel is proven to carry the demo modules and the newest detectors, not just the core. README quickstart lists all three scenarios.
- docs catch-up round. the written surface catches up with the shipped one. ARCHITECTURE's mcp_server entry now describes the real 19-tool inventory (grouped by concern); TUTORIAL's MCP section lists the tool surface with the recidivist/drift entry points; RECIPES gains two recipes - alignment neighbours (similar) for "which run is this one like?" and PSI drift windows for "is the fleet changing behaviour?". No code changes; docs validated against the tool list the tests pin.

## v0.69

- MCP context + curve (tools #18 and #19). budget-pressure analysis over stdio. `context` replays a recorded trace through a budgeted window (dry run): what survives eviction, fact recall, tokens saved; `curve` sweeps a geometric budget grid and returns the recall curve - "what does shrinking this run's window cost?" is now a tool call, not a shell-out. 5 new tests incl. tight-vs-loose budget eviction ordering and curve monotonicity.

## v0.68

- streaming contract + metrics audit. the streaming monitor's verify-step classification pinned directly (meta flag wins, non-tool steps never verify, tool-name markers enumerated, plain mutations excluded) - streaming.py to 100%. metrics.py audited at 100%: mode counters are data-driven, so every new detector surfaces in the Prometheus export automatically - no changes needed. 40b. **v0.72 — example smoke + checkout hygiene** ✅ (delivered): examples/flaky_agent.py wrote its HTML report into the current directory (same pollution class `approximately test` had) - it now writes next to the trace via `TraceStore()` (honors APPROXIMATELY_HOME), and a subprocess smoke test runs the example in isolation asserting FM-1.3 attribution, the report landing in the store, and no checkout leakage.
- MCP counterfactual + predict (tools #16 and #17). the deep-analysis surface is fully reachable over stdio. `counterfactual` runs leave-one-out attribution - which step's removal eliminates each mode (root cause vs symptom), distributed-cause verdict and causal ranking; `predict` mines the store's other traces for failure-precursor patterns and returns a probability with contributors and verdict. 5 new tests.

## v0.67

- MCP similar + drift (tools #14 and #15). the last CLI/MCP surface gaps close. `similar` returns the alignment-nearest traces to a given run (structure aware sequence alignment, score in [0,1]); `drift` computes the Population Stability Index between the oldest and newest windows of a store with the biggest shifted actions. An MCP client can now ask "what does this run look like?" and "is the fleet's behaviour shifting?" without shelling out. 6 new tests.

## v0.66

- per-select query memoization. the query DSL evaluated every field mention eagerly - an expression mentioning ``mode`` twice re-ran the full detector suite twice per trace. ``select()`` now shares a per-select memo keyed by (trace, field), so heavy fields (mode, agents, tokens, duration) pay once per trace no matter how often the expression mentions them; bare ``parse()`` keeps the eager behavior for single-use predicates. perf-gate gains a third gate: a double-mention ``mode`` filter over a 10k-trace store (109 ms against a 2 s budget). 4 new tests, including a detector-call counter that pins 3 traces x 2 mentions = 3 runs, not 6.

## v0.65

- TUTORIAL.md. a ten-minute record -> attribute -> bisect -> guard -> fleet-tutorial whose every command is already exercised by the walkthrough tests - the tutorial cannot silently drift from the tool. README links it above the design document.
- supply-chain hardening round. every GitHub Actions reference is SHA-pinned (checkout, setup-python, upload/download-artifact, pypa publish) - a mutable tag can no longer drift into the release path. New `security` CI job: bandit over `src` with zero findings expected (the six intentional adapter fallbacks now carry reasoned `# nosec B110` marks) and a regex secret scan over src, workflows and packaging metadata. SECURITY.md gains the provenance story.

## v0.64

- fuzz round 4 + bounded key reads. the newest surfaces (recidivist filter, shared verdict ladder, MCP cluster tool) fuzzed with garbage thresholds, corrupted integrity blocks and hostile key paths — every probe contained, corpus pinned as a regression gate. One real find: `--key-file` had no size bound, so a pointer at a huge regular file was read whole into memory; `load_key` now refuses anything over 4096 bytes (device nodes were already excluded by `is_file`). 6 new tests; SECURITY.md documents the cap and the fuzz doctrine.
- Windows correctness: the sharing clash, fixed at the root. the mystery "Windows runners keep wedging" was two real bugs in a chain. (1) `store.save` used a bare `os.replace`; on Windows that refuses with PermissionError while any reader holds the destination (POSIX allows it) — the concurrent-save test hit it every few CI runs. Now replaced by `_replace_bounded`, a bounded retry that absorbs the microsecond-wide reader window and still raises through when the clash persists. (2) When that error escaped, the test's reader thread - non-daemon, never signalled - kept pytest from exiting for 40+ minutes: the "hang" was a zombie interpreter, not a slow suite. The test now runs its reader as a daemon inside try/finally. (3) Belt and braces: pytest `faulthandler_timeout` dumps every thread's stack if any test stalls; CI Test step gets `timeout-minutes: 12` and the Demo smoke step 5. 2 new tests, including a flaky-replace simulation that pins the retry semantics cross-platform.

## v0.63

- llamaindex edge tests. typed-span lifecycle (RetrieverSpan/LLMSpan through new_span/exit/drop), hostile spans that raise in every hook (never break the query), `_parse_call` contract (dict-repr kwargs, no-space whole-name, freeform input fallback), `_preview` json-fallback quoting, and `wire()` accepting a manager directly. llamaindex stays 92% (remaining lines need framework-level mocks - diminishing value, documented and accepted).
- MCP cluster tool (tool #13). recidivist failure-mode clustering over stdio - attributes every trace and groups failures by (mode, tool-set), with the CLI's `min_size` recidivist threshold, `by_agent` switch, query-expression filter and a top-N. The MCP surface now answers "what keeps failing and through which tools / which agents" without shelling out. 7 new tests.

## v0.62

- one verdict payload everywhere. `integrity.verdict_payload()` is now the single source of truth for the verification ladder; the CLI (`verify <id> --json`) and the MCP `verify` tool render the same object — detail, chain finals, rollback flag, ledger health — instead of the MCP tool's bare `{trace, verdict}`. The MCP tool gains `key_file` for HMAC-keyed traces, and a wrong-key match is honestly `wrong-key` (exit 3, locked-not-broken) instead of masquerading as TAMPERED. 6 new tests.

## v0.61

- `verify <id> --json`. the single-trace integrity check joins the --all audit in speaking machine. Every rung of the six-exit-code ladder now emits one JSON object with a `verdict` field (intact / unsigned / keyed / tampered / rolled-back / ledger-broken) - a CI job can branch on the verdict instead of grepping prose. Text output unchanged. 5 new tests, including a deterministic rolled-back fixture.

## v0.60

- the recidivist filter. `agent_scorecard(min_failed=)` keeps only agents with at least N failed traces - one flaky run is noise, a repeat offender is a fleet problem. Exposed as `stats --by-agent --min-failed N` on the CLI and `scoreboard.min_failed` on MCP, so every surface asks the same question. The MCP handshake version now reads the installed distribution instead of a hardcoded 0.37.0 that had gone stale. 7 new tests.

## v0.59

- MCP server coverage to 100%. the remaining 18 uncovered lines closed - attribute/verify/bisect missing-trace tool errors, the survey and query handlers, the generic (non-KeyError) tool-exception branch, `cmd_mcp`'s scripted-stdio entry with the served-count report, and the empty-string EOF shutdown path. mcp_server 88% -> 100%; suite 701 tests. 31b. **v0.61 — adapter dispatch tests (no frameworks)** ✅ (delivered): fake crewai event bus + fake SDK spans drive the real dispatch logic locally (the contrib CI job covers the real packages): register/deregister across layouts, tool/llm/ kickoff event handling, "outcome owned by the caller" contract, langgraph full callback cycle incl. orphan tool-end and depth floor, agents_sdk span-type routing + trace-name takeover. crewai 66% -> 92%, langgraph 76% -> 92%.
- attribute --min-confidence. the per-detection admission floor is tunable for noisy environments; the knob can only raise it (max with the built-in 0.5), so a caller cannot weaken attribution by accident. Above every confidence the report falls back to the honest OTHER verdict. Wired through the CLI (single + --all) and the API. 4 new tests.

## v0.58

- the synthetic corpus carries agent identity. every step in docs/mast-bench-synth.jsonl is stamped agent=hyperagent (generator change + regeneration, same SEED), so the CI bench runs exercise the Step.agent paths - scorecard, reports, digest snapshots - on every run. Labels and floors untouched: attribution is mode-level and no synth scenario keys the identity-reading detectors. 3 new tests.66. **v0.57 — runner-up hypotheses carry their fixes** ✅

## v0.57

- HyperAgent schema tests. the log-line trajectory parser (`_hyperagent_turns`, the schema behind one of the corpus sources) had zero direct coverage (mastdata 80%); now pinned line-by-line - marker accumulation, continuation lines, pre-marker drops, empty-body markers, dict-schema routing-by-first-element, 2000-char truncation, and a convert_mast end-to-end roundtrip with real annotation options. mastdata coverage 80% -> 99%. 29b. **v0.58 — CLI sweep tests** ✅ (delivered, #121): every remaining command exercised end to end against a seeded store (similar, calibrate, counterfactual, drift, optimize, repair --apply, verify --all --json, clean, metrics --prometheus, curve, export-dataset, predict, cluster, taxonomy) - argument-wiring drift now fails CI. Real UX bug fixed en route: `calibrate` on a multi-label dataset crashed with a bare TypeError; it now exits 1 with "use benchmark --multi-label". cli.py coverage 86% -> 90%.
- runner-up hypotheses carry their fixes. the HTML Runner-up card grows a collapsible `<details>` block per runner-up ("If it was actually FM-x.y") listing that mode's engineering fixes - the next-best hypothesis now comes with its own action list. 2 new tests.

## v0.56

- MCP attribute explain. the attribute tool gains `explain: true` - the Bayesian fusion arithmetic (prior log-odds + per-detection LLR) rides along in the payload, so a verdict fetched over MCP is auditable as arithmetic, not vibes. Opt-in flag; default payload unchanged.
- MCP trend gains the agent dimension. the `trend` tool accepts an optional `agent` name and returns that agent's per-day rollup (steps/errors/ failed-of-touched) with its own Theil-Sen verdict - parity with `fleet --trend --agent`; without the param the fleet-level summary is unchanged. 1 new test. This merge releases v0.56.0.

## v0.55

- perf gate covers the agent wave + release provenance documented. perf_gate gains an agent-wave section (scorecard + markdown render on a 10k-step trace, 5 s budget - observed 0.08 s) alongside the attribution budget; SECURITY.md documents release provenance (autotag/ release workflows, scoped tokens, OIDC, the short allow-list of actions). 1 new test. This merge releases v0.55.0.

## v0.54

- buffer / audit findings. fixture building surfaced real detector-fitness lessons (homogeneous template turns trip the restart detector; harness echoes amplify shingle similarity; a pure loop legitimately exhibits FM-1.3 + FM-2.1, as the real gold double-labels) - documented in the generator and LEADERBOARD. 27b. **v0.55 — README capabilities completion** ✅ (delivered, #119): the capabilities table now carries every post-v0.34 capability (bisect, doctor, fleet trend gate, query DSL + stats, the 9-tool MCP server, attribution quality gates); the stale "7 tools" history row corrected to 9 (CLI parity). Taxonomy claim re-verified: 14 real modes + OTHER.
- fleet dashboard embeds the digest trend. `fleet --fleet-html --digest-dir DIR` renders the day-level fleet trend above the store cards - sparkline, Theil-Sen verdict badge with slope, per-day traces/rate table. Without a digest dir the page is unchanged. 5 new tests.

## v0.53

- ARCHITECTURE.md. the module map and evidence pipeline for contributors - recorder -> store -> integrity, the two exclusive detector families, Bayesian fusion, replay/repair, fleet ops, MCP - plus five invariants worth keeping, counts verified against the registries.
- MCP tool #12 `scoreboard`. the agent wave reaches stdio clients - per-agent steps/tool calls/ errors/tokens/failed-traces/touched-failure-rate for a store, with an optional query-expression filter (the full DSL, `agents contains ...` included) and optional top-N. Tool count 11 -> 12; 5 new tests.

## v0.52

- packaging CI job. `python -m build` in CI, then a clean-venv smoke install of the wheel (version banner + two-step recording) and artifact upload; the packaging job passed on its own PR. The PyPI path is validated on every PR without tagging - a release is now: Trusted Publishing setting + tag `v0.49.0` + push.
- release. this merge. 859 tests, 11-tool MCP, gates green, autotag releases it on merge.

## v0.51

- synthetic attribution regression fixture. `scripts/make_synth_corpus.py` (seeded, byte-stable) generates 180 prose records whose failure modes are planted by construction - FM-1.3/2.1/2.6/3.2 at P 1.00 / R 1.00 with tight Wilson intervals; `bench_gate.py --synth` + `bench-synth-floors` (floors at 0.95) fail CI on any detector drop, and a determinism test pins byte-identical regeneration. Honest framing enforced in docs: a canary for regressions, never real-world performance; FM-2.3/FM-3.1 deliberately absent.
- automatic releases shipped + v0.51 itself. v0.50.0 was released end-to-end by the new pipeline (tag → build → GitHub Release with generated notes and dist assets); autotag now fires on this very merge's version bump. Tutorial refresh covers explain, runner-ups, agent identity, and the bench-gate action.

## v0.50

- release readiness. package version aligned to the changelog (0.3.0 → 0.49.0 in pyproject + `__version__`), and `docs/ci-integration.md` now documents the attribution-quality gate and the fleet trend gate alongside the regression-guard workflow.
- `approximately explain` mode deep dives. per-mode "what does this mean for my agent" pages - definition, published MAST share, watching detectors, engineering fixes - with the detector column derived from live registries (every detector class now carries its `mode_id`, so the bridge cannot drift from the code). `explain` prints an overview table; `explain FM-1.3` the deep dive; unknown ids exit 1 with the valid id list. MCP grows to 10 tools with the same content. 10 new tests incl. registry-size drift guards.
- the attribution gate ships: `bench-gate` + GitHub Action. gate logic moves from scripts/bench_gate.py into approximately.benchgate with a `bench-gate` CLI command (dataset + floors -> exit 1 on breach); the script stays as a thin shim. A composite action.yml lets any repo gate its own dataset via `uses: B1ueMu3ic4m/approximately@v0` (install-from: source for this repo). CI dogfoods the action both ways on committed fixtures (examples/action/): positive clears, impossible floor fails the step and the job asserts the failure. 6 new tests.
- per-agent identity + agent scorecard. `Step.agent` with chain-safe serialization (unset agent omitted from to_dict, so pre-agent stores keep verifying; set agent is hash-covered and edits break the chain). `Recorder(agent=...)` + per-call `agent=` overrides; inter-agent messages stamp the sender. Withholding/ignored-input/role detectors read the field first with meta fallback for old traces. `stats --by-agent` rolls up steps/tokens/errors/touched-trace failure rate per agent ("unattributed" bucket keeps instrumentation gaps visible). 8 new tests.
- adversarial round: untrusted agent identity + gate integrity. hostile agent names (script payloads, backtick runs, fence-breakers, NUL, homoglyphs, bidi overrides, 10k chars, whitespace) driven through HTML reports, markdown reports, the scorecard, detectors, and the store roundtrip - found and fixed a real markdown fence-breaking vector (timeline fence now CommonMark-sized above any backtick run inside) and a silently-unfailable gate (NaN/Infinity floors now refused with offending JSON paths). Agent identity shows in both report renderers. 9 new tests + SECURITY.md rows; 10k-step perf smoke under 5 s.
- `verify --all --strict` / `--quiet`. default batch semantics stay "nothing is broken" (unsigned records pass with a note); strict mode enforces "every record must carry verifiable evidence" and fails on unsigned and keyed-locked records too - the cron/CI policy gate. `--quiet` drops per-trace rows for cron mailboxes; JSON gains a `strict` field. 4 new tests.
- docs/RECIPES.md task cookbook. ten task-shaped recipes (instrument in 5 lines, agent scoreboard, attribute+bisect+explain, regression tests, CI attribution gate via the action, nightly integrity cron with strict verify, fleet trend gate, query DSL, MCP client config, local-model judge). Every command spot-checked against the CLI surface; linked from the README next to the tutorial.
- per-agent observability: Prometheus counters, recidivist agents, label crash fix. `metrics --prometheus --by-agent` emits per-agent step/tool/ error/token/failed-trace counters plus touched-failure-rate gauges (agent names label-escaped); `cluster --by-agent` lists recidivist AGENTS by failed-trace participation with a JSON mode. Found and fixed a pre-existing crash: `metrics --prometheus --label k=v` died with AttributeError because the CLI passed raw strings to a dict API - labels now parse with a real error message for malformed pairs. 7 new tests.
- agent wave completion: agents in the HTML surfaces. single-trace reports gain an "Agents in this run" card (hidden for single-identity runs, names escaped); the fleet dashboard grows a "Busiest agents" table per store (steps/errors/touched-fail-rate); `fleet --json` and webhook payloads carry `top_agents`. 5 new tests.
- per-agent fleet trend. digest snapshots now carry each store's top-3 busiest named agents; `fleet --trend --agent NAME` plots one agent's steps/errors/ touched-fail-rate per day with its own Theil-Sen verdict (not the fleet's) and honors --fail-on-worsening. Untrusted-digest discipline kept (torn lines skipped, malformed fields read as zero, zero day = "not observed" documented in help + recipes). 6 new tests.
- runner-up hypotheses. attribution is a ranking, not an oracle - FailureReport now carries `runner_ups` (other modes the detectors fired for, with detection count and max confidence), shown via `attribute --top N`, in `to_dict`, and in the MCP attribute payload. Default output stays quiet. 5 new tests.
- docs/RELEASE.md runbook. pre-tag checklist (the full local gate list), version-bump contract (pyproject + __init__ must match), tag/push mechanics, what the Release workflow does (Trusted Publishing, no tokens), the clean-venv post-check, and the yank-and-patch rollback path.
- query DSL `agents` field. `agents contains 'researcher'` selects traces where a named agent performed a step (distinct Step.agent values; unattributed steps contribute nothing). Composes with the existing predicates; the unknown-field error now lists the new field. 5 new tests.
- the Release workflow creates the GitHub Release. pushing a v* tag now produces BOTH the PyPI publication and the Releases-page entry (auto-generated notes from merged PRs, sdist + wheel attached) - previously the workflow only published to PyPI, so the Releases page would have stayed empty even after tagging. RELEASE.md documents the empty-page cause honestly: versions were bumped in code, tags were never pushed. ---
- fully automatic releases. a new `autotag.yml` watches main - when a merge changes the pyproject version it tags it and dispatches `release.yml` (which gained a `workflow_dispatch` trigger for exactly this; a GITHUB_TOKEN tag push cannot trigger workflows, hence the explicit dispatch). The pipeline now creates the GitHub Release first and treats PyPI as best-effort (`continue-on-error`): token path if PYPI_API_TOKEN exists, Trusted Publishing fallback, a notice instead of a failure until credentials land. RELEASE.md rewritten around the no-human-steps flow.
- runner-up hypotheses in the human-facing reports. HTML reports gain a "Runner-up Hypotheses" card and Markdown reports a matching section (mode, label, detection count, max confidence) - completing v82, where only the CLI/JSON/MCP surfaces carried them. Hidden when the detectors fired for the primary mode alone. 4 new tests.
- doctor detects legacy agent identity. stores recorded before v0.50 carry the actor in step `meta["agent"]`; the doctor now lists affected files (informational, never an unhealthy verdict) with the migration hint - re-saving the trace moves identity to `Step.agent`, which detectors, scorecard, and reports read first. 4 new tests.
- configurable busiest-agents window. `fleet --top-agents N` sizes the per-store busiest-agents snapshot (default 3) for watch digests, dashboards, and fleet JSON; `survey(top_agents=N)` in the API. The trend visibility limit is restated in help text: `fleet --trend --agent` sees only agents inside the window. 4 new tests.
- fuzz round 3: two real crashes found and fixed. seeded garbage through the newest boundaries (digest snapshots, floors JSON, DSL agents field, MCP bench_gate). Found: a valid-JSON-but-list digest line crashed trend_days (only JSONDecodeError was guarded), and a string-typed sample_f1 / mode floor crashed check_floors with TypeError instead of failing the gate. Fixes: non-object snapshots skipped, every floor value coerced through a finite -number check (non-numeric floors are violations, never comparisons), bench-gate demands a floors JSON object. Floors files can no longer crash or silently pass. 4 new tests (858 total).

## v0.49

- doctor --fix. removes what the hygiene checks flagged — stale writer locks and leftover temp files — and never touches record data, the ledger, or digests; the removal note goes to stderr so --json stdout stays parseable. Exit code flips to healthy when findings clear.

## v0.48

- MCP trend + stats tools. the MCP server reaches full CLI parity at nine tools — `trend` (day-level digest analytics) and `stats` (query-selection aggregates) reuse the fleet/query modules directly; a missing digest dir reads as an empty history, not an error.

## v0.46

- README walkthrough regression tests. every quickstart/capabilities command executed against a fresh demo-seeded store with its promised output asserted — doc drift fails CI. Found and fixed real walkthrough pollution on the way: `test` generates guard files in the CWD, so the walkthrough now runs it from a scratch directory.

## v0.45

- adversarial-input fuzz round. seeded, deterministic fuzz over every parser boundary — 300 random query expressions (QueryError or callable, never leaks), 5000-deep nesting (cap, not RecursionError), corrupt/bytes store records through the doctor, 200+ protocol-edge MCP lines, random prose turn soup under a timing bound. Fixed seeds reproduce failures.

## v0.44

- attribution regression gate. `scripts/bench_gate.py` + `docs/bench-floors.json` — gold-corpus per-mode P/R/F1 floors enforced by the CI bench-gate job; a detector refactor that silently degrades attribution fails CI (provably fires on pre-v0.38 main: FM-1.3 R 0.14 < 0.60).

## v0.41

- store doctor. `doctor STORE [--digest-dir DIR] [--json]` — parseable-record walk (corrupt files, id/filename mismatches, unsigned records), evidence-ledger chain verification, stale writer locks (>1 h) and leftover temp files, and digest-history monitoring gaps + torn-line counts. Exit 1 on any finding — CI-friendly. 7 tests cover the corrupt/ tampered/stale/gap paths. 17b. **v0.47 — demo loop scenario** ✅ (delivered): `demo --scenario loop` — a planner→navigator→editor crew stuck in an args-evolving cycle; the exact-fingerprint RepeatDetector cannot fire, so the cycle detector is the only thing that catches it (v0.38 end to end), HTML report included.

## v0.40

- digest trend analytics. `fleet --trend --digest-dir DIR` — per-day fleet state from the JSONL history (last snapshot of each day), trace-weighted failure rate, top-mode counts, sparkline, and the same Theil-Sen verdict the survey uses applied to day rates; `--json` for machines and the existing `--fail-on-worsening` doubles as the trend CI gate. Digest files are treated as untrusted input: torn tail lines and corrupt timestamps fall back to the file-name day stamp.

## v0.39

- first-fault bisect. `bisect FAILED SUCCESS [--floor F] [--json]` — earliest *material* divergence on the NW edit script (mutations at similarity ≥ floor count as timestamp noise; deletions/insertions always material), plus the worst-5 divergence ranking. 3000×3000-step stress: 2.0 s, fault pinpointed at the exact flip step (similarity 0.09).

## v0.38

- cycle-grade repetition (FM-1.3 step 2). longest back-to-back repeated tool block (period 2–6) over non-errored calls; fires when the cycle consumes ≥16 calls. Multi-agent inner loops (planner→navigator→editor) evolve args every turn, so exact fingerprints never match — the cycle is the real signal. Corpus: FM-1.3 R 0.14 → 0.71 at P 1.00 (tp 1→5, fn 6→2, fp 0); corpus sample P 0.55, F1 0.46. Threshold calibrated on the only labeled corpus (n=27, intervals wide). Security: ProseRepeatDetector's O(T²) SequenceMatcher queue was a crafted-record DoS (400 distinct 1.5k turns → 36.6 s); a shingle-Jaccard prefilter (floor 0.3, conservative against the 0.92 ratio) bounds it to 0.23 s — 157× — with the true-positive path unchanged.

## v0.37

- zero-dependency MCP stdio server. : JSON-RPC 2.0 over stdio exposing list/query/attribute/verify/survey as MCP tools.

## v0.36

- Mermaid export. : `report --mermaid` rendering the attributed trace as a mermaid sequenceDiagram for docs/PRs.

## v0.35

- Wilson score intervals on benchmark metrics. : the leaderboard's P/R/F1 are point estimates on small n; report 95% Wilson intervals for precision/recall so honesty about uncertainty is built into the benchmark output.

## v0.34

- SARIF export. — already shipped (v0.4): roadmap audit found `attribute --sarif` live with GitHub code-scanning integration; superseded by the fleet watch loop below.
- fleet watch/digest loop. `fleet --watch SECONDS --digest-dir DIR` polling survey() into daily JSONL snapshots with `--keep-days` rotation and `--iterations` for cron-friendly bounded runs.

## v0.33

- query DSL. recursive-descent expression language over the store — `query "mode == FM-2.1 and confidence >= 0.7"`-style selection with `--json`, eval-free closures, depth/length caps against parser attacks.

## v0.32

- `diff --json` + divergence ranking. per-entry char similarity on the NW edit script, worst-first `divergences()`, machine output for CI gates. (The planned "trace diff" already shipped in v0.6 — this round upgrades it instead of duplicating it; a duplicate subparser built during the round was caught by the new tests before push.)

## v0.31

- outcome-signal verification (FM-3.2 step 2). `ProseOutcomeVerifyDetector` — completion-claim vocabulary (execution-shaped language excluded) + zero outcome signals in the record = unchecked claim. First nonzero FM-3.2: P 0.54 · R 0.64 · F1 0.58; corpus sample F1 0.29 → 0.43.

## v0.30

- FM-2.6 action-continuity guards. scaffold-echo guard + entity-token continuity (path/stem/bare-name variants) + thought-context continuity; FM-2.6 precision 0.07 → 0.33 (fp 14 → 2), F1 0.12 → 0.40, recall held; corpus sample precision 0.30 → 0.44. Bonus: stress test exposed an O(n²)-backtracking DoS on megabyte turns — prose analysis now bounded at 8k chars/turn (1 MB turn: >20 s → ~1 ms).

