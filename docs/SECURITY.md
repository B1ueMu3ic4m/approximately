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
| Generated regression tests | Code injection via trace content | Trace content travels as base64, never interpolated into code; the only interpolated values are MAST mode ids from the fixed taxonomy. |
| Secrets | Leakage | No telemetry, no network calls in the core, no secrets in repo (scanned in CI). |

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

## Reporting

Open a private security advisory via GitHub → Security → Report a
vulnerability. We treat forged evidence in an incident postmortem as a
critical-severity report.
