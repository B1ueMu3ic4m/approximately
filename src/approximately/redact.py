"""Secret scrubbing: sanitized share-copies of recorded traces.

Traces are evidence, and evidence gets shared — pasted into an issue,
attached to a postmortem, handed to a colleague. Tool results routinely
carry credentials the agent was holding when the run went sideways.
:func:`redact_trace` produces a *share copy*: a deep copy with secret
matches scrubbed, a fresh id, and a fresh integrity chain, leaving the
original file byte-for-byte untouched.

The scrubbed fields are the free-text surfaces (results, thoughts,
errors, task, final output, step args values). Structured metadata
(``meta``, ``step.meta``) passes through minus the integrity block —
the recorder never writes secrets there, and a copy keeps the budget
and attribution context that makes the evidence readable.
"""

from __future__ import annotations

import copy
import re
import time
from typing import Any, Dict, List, Optional, Pattern, Tuple

from .trace import Trace

# Curated high-signal secret shapes, tried in order. Each match is
# replaced with ``[REDACTED:<name>]`` so the postmortem reader can see
# *what kind* of secret was being carried, never its value.
_BUILTIN_SOURCE: Tuple[Tuple[str, str], ...] = (
    ("aws_key", r"\bA[SK]IA[0-9A-Z]{16}\b"),
    ("gcp_key", r"\bAIza[0-9A-Za-z_\-]{35}\b"),
    ("github_token", r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"),
    ("openai_key", r"\bsk-[A-Za-z0-9_\-]{20,}\b"),
    ("slack_token", r"\bxox[baprs]-[A-Za-z0-9\-]{10,}\b"),
    ("jwt", (r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"
             r"\.[A-Za-z0-9_\-]{5,}\b")),
    ("bearer", r"(?i)\bbearer[ \t]+[A-Za-z0-9._~+/=\-]{16,}"),
    ("private_key", (r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----"
                     r"[\s\S]*?-----END [A-Z0-9 ]*PRIVATE KEY-----")),
)

BUILTIN_PATTERNS: Dict[str, Pattern[str]] = {
    name: re.compile(src) for name, src in _BUILTIN_SOURCE
}

REDACTED_FMT = "[REDACTED:{name}]"


def _merge_extra(table: Dict[str, Pattern[str]],
                 extra: List[str]) -> None:
    """Fold ``name=regex`` / bare ``regex`` additions into the table,
    in place. Raises ValueError on an uncompilable or empty regex."""
    for i, raw in enumerate(extra):
        name, sep, regex = raw.partition("=")
        if not sep or not name.strip():
            name, regex = f"custom-{i + 1}", raw
        name = name.strip()
        if not regex:
            raise ValueError(f"pattern {name!r}: empty regex")
        try:
            table[name] = re.compile(regex)
        except re.error as exc:
            raise ValueError(f"pattern {name!r}: {exc}") from exc


def compile_patterns(
    extra: Optional[List[str]] = None,
    only: Optional[List[str]] = None,
) -> Dict[str, Pattern[str]]:
    """The pattern table to run: builtins (or the ``only`` subset of
    them) plus any ``name=regex`` / bare ``regex`` additions.

    Raises ValueError on an unknown ``only`` name or an uncompilable /
    empty extra pattern — refusal, not a half-scrubbed copy.
    """
    if only:
        unknown = [n for n in only if n not in BUILTIN_PATTERNS]
        if unknown:
            raise ValueError(
                "unknown pattern(s): "
                + ", ".join(sorted(unknown))
                + " (builtins: " + ", ".join(sorted(BUILTIN_PATTERNS)) + ")")
        table: Dict[str, Pattern[str]] = {
            n: BUILTIN_PATTERNS[n] for n in only
        }
    else:
        table = dict(BUILTIN_PATTERNS)
    _merge_extra(table, list(extra or []))
    return table


def _scrub(text: str, table: Dict[str, Pattern[str]],
           hits: Dict[str, int], fmt: str = REDACTED_FMT) -> str:
    out = text
    for name, pattern in table.items():
        out, n = pattern.subn(fmt.format(name=name), out)
        if n:
            hits[name] = hits.get(name, 0) + n
    return out


def _scrub_value(value: Any, table: Dict[str, Pattern[str]],
                 hits: Dict[str, int], fmt: str = REDACTED_FMT) -> Any:
    """Scrub recursively through dicts/lists; keys are never rewritten
    (a renamed JSON key breaks consumers; a secret in a *key* is rare
    and better handled by a custom pattern matching the whole blob)."""
    if isinstance(value, str):
        return _scrub(value, table, hits, fmt)
    if isinstance(value, dict):
        return {k: _scrub_value(v, table, hits, fmt)
                for k, v in value.items()}
    if isinstance(value, list):
        return [_scrub_value(v, table, hits, fmt) for v in value]
    return value


def redact_trace(
    trace: Trace,
    table: Optional[Dict[str, Pattern[str]]] = None,
    replacement: Optional[str] = None,
) -> Tuple[Trace, Dict[str, Any]]:
    """Return ``(share_copy, report)``; the input trace is untouched.

    The scrubbed surfaces are the free-text ones: ``task``,
    ``final_output``, and each step's ``result``, ``thought``, ``error``
    and ``args`` values (recursively). The copy gets a fresh id, its
    integrity block is stripped (the store re-signs derived artifacts
    on save with *our* key — the original's chain stays with the
    original), and ``meta["redacted"]`` records provenance: source id,
    time, per-pattern hit counts, total. ``replacement`` overrides the
    marker format — a literal (``[REDACTED]``) or a template keeping
    ``{name}`` for the pattern that fired.
    """
    import uuid

    table = table or BUILTIN_PATTERNS
    fmt = (replacement or REDACTED_FMT).strip() or REDACTED_FMT
    hits: Dict[str, int] = {}
    share = copy.deepcopy(trace)
    share.task = _scrub(share.task, table, hits, fmt)
    if isinstance(share.final_output, str):
        share.final_output = _scrub(share.final_output, table, hits, fmt)
    for step in share.steps:
        step.result = _scrub(step.result, table, hits, fmt)
        if isinstance(step.thought, str):
            step.thought = _scrub(step.thought, table, hits, fmt)
        if isinstance(step.error, str):
            step.error = _scrub(step.error, table, hits, fmt)
        step.args = _scrub_value(step.args, table, hits, fmt)
    share.id = uuid.uuid4().hex[:12]
    if isinstance(share.meta, dict):
        share.meta.pop("integrity", None)
        share.meta["redacted"] = {
            "from": trace.id,
            "at": time.time(),
            "hits": dict(hits),
            "total": sum(hits.values()),
            "patterns": sorted(table),
        }
    report = {
        "source": trace.id,
        "share_id": share.id,
        "hits": dict(hits),
        "total": sum(hits.values()),
        "patterns": sorted(table),
    }
    return share, report
