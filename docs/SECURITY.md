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

The untrusted-input boundaries are fuzzed per wave (tests `test_fuzz`,
`test_v45_fuzz`, `test_v88_fuzz_round3`, `test_v98_fuzz_round4`):
round 4 covers the recidivist filter, the shared verdict ladder and
the cluster tool. Contract: documented errors or clean skips, never a
crash that escapes as a protocol fault.
