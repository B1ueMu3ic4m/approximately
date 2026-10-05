"""The handoff brief: what the next engineer (or agent) actually reads.

A failing run lives in a store with a chain, an attribution, a burn
and maybe an annotation trail. The handoff composes those into one
markdown page — what failed, why we think so, what it cost, whether
the evidence is trustworthy, where the full record lives. With
``--redact`` the whole brief is rendered from a sanitized share-copy,
so the page is safe to paste before it exists.
"""

from __future__ import annotations

import time
from typing import Any, List, Optional

from .trace import Trace


def _fmt_cost(trace: Trace, prices: Optional[dict]) -> Optional[str]:
    if not prices:
        return None
    rate = prices.get(str(trace.model or "unknown"))
    if rate is None:
        return None
    tokens = sum(s.tokens for s in trace.steps)
    return f"${tokens / 1000 * rate:,.4f}"


def _first_failure(trace: Trace) -> Optional[Any]:
    for step in trace.steps:
        if step.error:
            return step
    if trace.success is False:
        return trace.steps[-1] if trace.steps else None
    return None


def _redact_line(text: Optional[str], table: Optional[dict],
                 limit: int = 200) -> str:
    out = " ".join((text or "").split())
    if table:
        from .redact import _scrub

        hits: dict = {}
        out = _scrub(out, table, hits)
    if len(out) > limit:
        out = out[: limit - 3] + "..."
    return out or "(empty)"


def _evidence_lines(trace: Trace, store: Any, table: Optional[dict]
                    ) -> List[str]:
    """The trust section: chain verdict plus the annotation trail."""
    from .integrity import verify

    lines: List[str] = []
    verdict = verify(trace).verdict
    chain = ("intact — safe to rely on" if verdict == "intact"
             else f"**{verdict}** — do not trust the record")
    lines.append(f"- hash chain: {chain}")
    notes = store.annotations(trace.id)
    if notes:
        last = notes[-1]
        verdict_txt = f"[{last['verdict']}] " if last.get("verdict") \
            else ""
        lines.append(f"- annotations: {len(notes)} on file; latest: "
                     f"{verdict_txt}"
                     f"{_redact_line(last.get('note', ''), table, 120)}")
    else:
        lines.append("- annotations: none on file")
    return lines


def _attribution_lines(trace: Trace, table: Optional[dict]
                       ) -> List[str]:
    """Mode id, reading and fixes for an attributed failure."""
    from .attributor import attribute

    lines: List[str] = []
    try:
        report = attribute(trace)
    except Exception:
        return lines  # poison step: the raw error above stands
    if report is None or not report.failed:
        return [("- attribution: none — unattributed failures are "
                 "exactly the ones needing eyes")]
    lines.append(f"- attribution: `{report.primary_mode.id}` "
                 f"({report.primary_mode.label})")
    if report.summary:
        lines.append(f"- reading: "
                     f"{_redact_line(report.summary, table)}")
    fixes = report.suggested_fixes or []
    if fixes:
        lines.append("- suggested fixes:")
        lines.extend(f"  - {_redact_line(f, table, 160)}"
                     for f in fixes[:3])
    return lines


def _failure_lines(trace: Trace, table: Optional[dict]
                   ) -> List[str]:
    """The diagnosis section: the failing step and the attribution."""
    step = _first_failure(trace)
    if step is None:
        return ["- nothing — this run passed (handoff for context)"]
    head = step.tool or step.kind
    lines = [(f"- step #{step.index} `[{step.kind}] {head}`: "
              f"{_redact_line(step.error or step.result, table)}")]
    lines.extend(_attribution_lines(trace, table))
    return lines


def brief(trace: Trace, store: Any,
          table: Optional[dict] = None) -> str:
    """Render the markdown brief; ``table`` (pattern name ->
    compiled regex) scrubs every free-text line first."""
    lines: List[str] = []
    title = _redact_line(trace.task, table, 70)
    lines.append(f"# Handoff: {title}")
    tokens = sum(s.tokens for s in trace.steps)
    latency_s = sum(s.latency_ms for s in trace.steps) / 1000.0
    prices = None
    try:
        from .prices import load_catalog

        prices = load_catalog(store.directory)
    except ValueError:
        prices = None  # corrupt catalog: the burn shows unpriced
    cost = _fmt_cost(trace, prices)
    from .trace import coerce_epoch

    when = time.strftime("%Y-%m-%d %H:%M:%S",
                         time.localtime(
                             coerce_epoch(trace.created_at)))
    outcome = ("success" if trace.success else
               "FAILED" if trace.success is False else "unknown")
    facts = [f"trace `{trace.id}`", f"model `{trace.model}`",
             f"{len(trace.steps)} steps", f"outcome: {outcome}",
             f"recorded {when}"]
    if tokens:
        facts.append(f"{tokens:,} tokens")
    if cost:
        facts.append(f"~{cost} at the store catalog")
    if latency_s:
        facts.append(f"{latency_s:.1f}s total tool latency")
    lines.append("")
    lines.append("- " + "\n- ".join(facts))
    lines.append("")
    lines.append("## Evidence")
    lines.extend(_evidence_lines(trace, store, table))
    lines.append("")
    lines.append("## What failed")
    lines.extend(_failure_lines(trace, table))
    lines.append("")
    lines.append(f"*Full record: `{store.directory}/{trace.id}.json` "
                 f"— verify with `approximately verify {trace.id}`*")
    return "\n".join(lines)
