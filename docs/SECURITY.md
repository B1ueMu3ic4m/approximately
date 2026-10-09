# Security model

approximately is a local-first evidence tool. This document is the threat
model: what it protects, what it explicitly does not, and how to report.

## Assets & trust boundaries

| Asset | Threat | Control |
|---|---|---|
| Recorded traces | Accidental or lazy tampering | **Unkeyed sha256 chain** stamped on every save; `approximately verify <trace>` recomputes and localizes the first altered step. |
| Recorded traces | **Adversarial forgery** (attacker with write access rewrites steps and re-computes the chain) | **HMAC-SHA256 chain** (`APPROXIMATELY_SIGNING_KEY` or `--key-file`). Verifying a keyed trace without the key returns `keyed` (locked, not broken); with the wrong key it returns `TAMPERED`. |
| Trace files on disk | Path traversal via crafted ids (`../../etc/passwd`) | `TraceStore._resolve` rejects ids containing parent segments; explicit paths must be real files. |
| Scaffolded projects | Directory escape via project name (`approximately new ../../evil`) | Names must match `^[A-Za-z0-9][A-Za-z0-9_.-]*$` and may not contain `..`. |
| HTML reports | Injection from untrusted trace content (tool results, thoughts) | Every dynamic value is HTML-escaped (`html.escape`, quotes included); fuzz-tested in `tests/test_report_escapes.py`. |
| Markdown reports | **Fence-breaking**: a backtick run in trace content closing the timeline code fence early, so the tail renders as live Markdown/HTML; newlines in agent names smuggling fence boundaries | The timeline fence is sized per CommonMark to exceed any backtick run inside it; agent names are whitespace-collapsed onto their step's single line. Fuzz-tested in `tests/test_v77_adversarial_agents.py`. |
| Attribution gate | **Silently unfailable gate**: `json` accepts NaN/Infinity, and a NaN floor compares False against every score — passing the gate forever | `bench-gate` refuses floors documents containing non-finite numbers (exit 1, offending paths listed). |
| Agent identity | Untrusted agent names from merged fleet stores flowing into reports, scorecards, and detectors | Escaped in HTML, fence-contained in Markdown, JSON-serializable rows in the scorecard; hostile names (homoglyphs, bidi overrides, 10k chars, NUL) are fuzz-tested. |
| Generated regression tests | Code injection via trace content | Trace content travels as base64, never interpolated into code; the only interpolated values are MAST mode ids from the fixed taxonomy. |
| Secrets | Leakage | No telemetry, no network calls in the core, no secrets in repo (scanned in CI). |
| Attribution pipeline | **Algorithmic-DoS via crafted records** (megabyte turns, pathological repetition) | Prose analysis bounded at 8k chars/turn; the O(T²) SequenceMatcher queue is prefiltered by shingle-Jaccard (a crafted 400-turn no-repeat record: 36.6 s → 0.23 s); a 2 MB MCP line is rejected in <1 s. Enforced by seeded fuzz (`tests/test_v45_fuzz.py`) and timing tests. |
| Query DSL / MCP line protocol | Injection or parser confusion from untrusted expressions/lines | Recursive-descent parser with depth (50) and length (4k) caps, eval-free closures; JSON-RPC envelope validated per field; garbage input answers `-32700`/`-32600`/`-32602` or is silenced, never crashes the loop (fuzz-covered). |
| Digest files / doctor input | Corrupt or hostile JSONL on disk | Torn tail lines skipped, corrupt timestamps fall back to the file-name day stamp; doctor classifies unparseable/bytes files as corrupt without crashing (fuzz-covered). |
| Attribution quality | **Silent regression** from a detector refactor | Gold-corpus CI gate (`scripts/bench_gate.py` + `docs/bench-floors.json`): per-mode P/R/F1 floors must hold or CI fails. |
| CSV export | **Formula injection**: a tool result starting `= + - @ <tab>` executing as a spreadsheet formula when the file opens in Excel/Sheets | Standard CSV-injection defense: those cells get a leading quote at write time (tool/agent columns too — foreign ids ride in through OTLP import). Leading-minus text is quoted as well: untrusted beats pretty. The JSONL exports stay lossless and are the archival path. |
| Evidence packs | Post-hoc swap of archive members | Every member's sha256 is recorded in `manifest.json`; a reviewer recomputes the list with `unzip`/`sha256sum`. Honest limit: the manifest is not a signature — an attacker with write access can re-pack and re-hash. The pack's tamper-evidence rests on the **chain inside `trace.json`** (verify it with `approximately verify` on the extracted record); the manifest defends against truncation and accidental corruption, not forgery. |
| Evidence packs | Zip bombs / path traversal in member names | Members are written, never read from untrusted archives: four fixed names, created by the tool. The evidence door never extracts a foreign zip. |
| Corrupt record files | **Silent deletion of evidence** by housekeeping | `doctor --fix` QUARANTINES unreadable records into `<store>/.quarantine/` with a jsonl manifest (file, parse error, moved_at) — bytes preserved for forensics, never unlinked; `clean --keep-breached` keeps budget-stamped runs past any retention cutoff. Poison files are not evidence: quarantine skips nothing it moves, but the guard never preserves an unreadable file. |
| Reliability/spend budgets | **Lie-by-subtraction**: digest rows with negative failure counts, or unpriced models silently valued at $0 | `failure_budget` clamps digest failures at zero (a budget that grows as the fleet burns is not a budget); the spend forecast and every budget ceiling count unpriced models in `unpriced_tokens` — a budget you cannot compute does not hold. Fuzz-pinned (`tests/test_v290_fuzz22.py`). |
| Webhooks | Replay, redirect, hostile pacing | http(s) scheme checked before urllib (file:// and custom schemes refused); HMAC-SHA256 over the exact body bytes (a fresh Request per retry attempt, so retries re-send the signed body, not garbage); retries capped at 3 with backoff capped at 4s and a `Retry-After` honored only up to 5s — a hostile header cannot stall a watch. |
| Query DSL `matches` | **ReDoS via crafted regex** (the pattern arrives on a command line) | Compiled at parse time; source capped at 256 chars; subjects truncated to 4k per evaluation; a bad regex is a loud parse error, never a silent no-match. Note: catastrophic backtracking inside the cap is not shielded — the pattern author is the local operator. |
| Redaction custom patterns | **ReDoS via operator-supplied `--pattern`** | Same stance as the query DSL: compile-time syntax check only, no shape policing (zero-dependency `re` has no timeout); the built-in eight shapes are linear by construction. A catastrophic custom pattern is self-inflicted — review what you hand the scrubber. Fuzz-pinned (`tests/test_v299_fuzz23.py`). |
| Digest delivery (`--post`) | **Secret exfiltration through the shift brief**: the page names task text verbatim, and a failed run's task routinely names the credential it was holding | `--redact` scrubs the payload (JSON mode) and the rendered page — including the posted body — through the builtin secret patterns before anything leaves the machine; `redact_text`/`redact_value` are public so every future rendering surface can hold the handoff's rule. Off by default: the local brief stays faithful evidence, the scrub is a deliberate act. |
| Webhook announcements (tail / fleet / spool / digest `--post`) | A receiver cannot tell a genuine alert from a forged one | HMAC-SHA256 over the exact body bytes travels in `X-Approximately-Signature` when `APPROXIMATELY_SIGNING_KEY` is set — the same `load_key` every poster uses. (v3.17.0 audit finding: `tail --webhook`'s help promised this and nothing read the variable; the promise is now kept and pin-tested.) |
| Retention (`retention --apply`) | **Housekeeping deleting evidence** the postmortem still needs | Two guards veto every retirement, checked at plan time and again at apply time (a plan is a snapshot, the store moves on): budget-stamped breach evidence and annotated traces never unlink. Unreadable files are counted and left for `doctor --fix`'s quarantine — retention never guesses at bytes it cannot parse. The MCP door deletes too, but only behind a two-flag gate (`apply` + `confirm`); both doors share one delete path with the same vetoes. |
| `webhook-serve` | **Unauthenticated log seeding**: an open receiver lets anyone write rows into the ops log | With a key configured (file or `APPROXIMATELY_SIGNING_KEY`) the receiver is verify-only: absent, malformed or wrong `X-Approximately-Signature` gets 401 and is never archived. With no key it archives and marks every row `verified: false` — an open tap, labeled as one. Bodies must be JSON objects; anything else is refused without crashing the server. Bodies larger than `--max-bytes` (default 1 MiB) are refused 413 **before the read** — a hostile Content-Length cannot buy a hostile read. Posts arrive on parallel threads; the bookkeeping serializes on a lock, so counters never lose a hit and archive lines never interleave (200-thread soak, exact counts). |
| `approximately init` / `new` | Overwriting user files, hostile trees | `init` never overwrites without `--force` (and `.gitignore` is append-only even then); files that cannot be written (a directory in the way, a read-only parent) report status `refused` and the rest of the scaffold proceeds. |

## Honest limits of the unkeyed chain

A plain hash chain proves that nothing changed *since signing* only
against accidental corruption. Because every input is public, an attacker
with write access can rewrite a trace and re-compute the chain. For
evidence that must survive a hostile environment, set a signing key:
HMAC chains are infeasible to re-compute without the secret.

## Concurrency

Shared stores are a supported deployment. Saves are atomic (temp file +
`os.replace`) and same-id writes serialize on a per-id lock file with
stale-lock recovery — a crashed writer cannot block the store forever,
and readers never observe partial writes.

## Explicitly out of scope

- The LLM judge path sends trace content to whatever endpoint you configure
  (`--judge` / `OPENAI_BASE_URL`). That endpoint sees the trace; approximately
  adds nothing to that trust decision — use a local model for sensitive runs.
- Executor imports (`approximately replay --executor pkg:mod`) execute code
  you name, exactly like `pytest` plugins. Only point it at code you trust.
- The host OS account's permissions bound the tool's; approximately never
  elevates.

## Release provenance

Tags are created by `autotag.yml` (repo-scoped `GITHUB_TOKEN`,
`contents: write`) from main's `pyproject.toml` version; releases are
built and published by `release.yml` from the tagged commit. Third
-party actions are limited to the well-known GitHub-owned steps
(checkout, setup-python, artifact upload/download) and
`pypa/gh-action-pypi-publish`. The PyPI publish runs OIDC Trusted
Publishing or an API-token secret — no long-lived credentials in the
repo. A malicious change to either workflow lands through a reviewed
PR like any other code change; the tag history and Release assets
are the audit trail.

## Reporting

Open a private security advisory via GitHub → Security → Report a
vulnerability. We treat forged evidence in an incident postmortem as a
critical-severity report.

## Key file reads are bounded (v0.64)

`--key-file` (and the MCP `verify.key_file`) refused non-regular
files already — `is_file()` keeps device nodes like `/dev/zero` out —
but a hostile pointer at an arbitrarily large *regular* file was read
whole into memory. Key files are now capped at 4096 bytes; anything
bigger raises instead (`ValueError`, or an MCP tool error), and the
fuzz corpus pins it.

## Fuzz rounds

The untrusted-input boundaries are fuzzed per wave (rounds 1-19
across `test_fuzz`, `test_v45_fuzz`, `test_v88_fuzz_round3`,
`test_v98_fuzz_round4`, `test_v132_fuzz_round7`,
`test_v212_otlp_fuzz`, `test_v237_fuzz_round16`,
`test_v245_fuzz_round17`, `test_v249_fuzz_round18`,
`test_v255_fuzz_round19`, and friends). Recent rounds cover the
CSV surface, the deep-doctor chain reads, the evidence pack, and
the compare door. Contract: documented errors or clean skips,
never a crash that escapes as a protocol fault.
