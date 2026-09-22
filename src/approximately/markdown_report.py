"""Postmortem-to-Markdown renderer: issue-ready failure reports.

The HTML report is for reading in a browser; this renderer emits the
same verdict as GitHub-flavored Markdown — paste-ready for an issue,
a PR description, or a incident channel. Escaping follows CommonMark:
user-controlled text is rendered inside fenced blocks or backticks so
it can never inject formatting.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, List

if TYPE_CHECKING:
    from .attributor import FailureReport
    from .trace import Trace


def _esc(text: str) -> str:
    """Neutralize Markdown-significant characters in user text."""
    for ch in ("\\", "`", "*", "_", "[", "]", "<", ">"):
        text = text.replace(ch, "\\" + ch)
    return text


def _lines(text: str, limit: int = 400) -> List[str]:
    return [line for line in text.splitlines() if line.strip()][:limit]


def _evidence_lines(report: "FailureReport") -> List[str]:
    lines: List[str] = ["### Evidence", ""]
    for det in report.detections:
        lines.append(f"- **{det.mode_id}** via {det.source} "
                     f"(confidence {det.confidence:.2f}), step "
                     f"#{det.step_index}")
        lines.extend(
            f"  - {_esc(evidence_line)}"
            for item in det.evidence
            for evidence_line in _lines(str(item))[:4])
    return lines


def _timeline_lines(trace: "Trace") -> List[str]:
    rows: List[str] = []
    for step in trace.steps:
        excerpt = " ".join(str(step.result).split())[:160]
        marker = "!" if step.error else " "
        who = " ".join(str(step.agent).split()) + " · " \
            if step.agent else ""
        rows.append(f"{marker} #{step.index:>3} [{step.kind}] "
                    f"{who}{step.tool or ''} {excerpt}".rstrip())
    # CommonMark fence sizing: a body line may itself contain backtick
    # runs (agent names and tool results are untrusted), so the fence
    # must be longer than any run inside it — otherwise the body closes
    # the fence early and the tail renders as live Markdown/HTML.
    runs = [len(run) for row in rows for run in re.findall(r"`+", row)]
    fence = "`" * max(3, max(runs, default=0) + 1)
    return ["### Timeline", "", f"{fence}text", *rows, fence]


def render_markdown(trace: "Trace", report: "FailureReport") -> str:
    """Issue-ready Markdown postmortem for one attributed trace."""
    verdict = _esc(report.primary_mode.label)
    lines = [
        f"## Postmortem: {verdict}",
        "",
        f"- **trace**: `{report.trace_id}`",
        f"- **outcome**: {'FAILED' if report.failed else 'passed'}",
        f"- **task**: {_esc(report.task)}",
        "",
        report.summary,
        "",
    ]
    lines.extend(_evidence_lines(report))
    if report.suggested_fixes:
        lines += ["", "### Suggested fixes", ""]
        lines.extend(f"{i}. {_esc(fix)}"
                     for i, fix in enumerate(report.suggested_fixes, 1))
    lines.append("")
    lines.extend(_timeline_lines(trace))
    if report.judge_used:
        lines += ["", "*Includes the optional LLM judge's verdict.*"]
    return "\n".join(lines) + "\n"
