"""Mermaid sequence-diagram export for traces.

One line per step renders a trace as a ``sequenceDiagram`` that
pastes directly into GitHub markdown, PR descriptions, or any mermaid
renderer — the postmortem picture without a screenshot. Attribution
detections appear as notes over the failing step. Everything
user-controlled is stripped of mermaid-breaking characters.
"""

from __future__ import annotations

from typing import List, Optional

from .trace import TOOL_CALL, Trace

_EXCERPT = 72


def _sanitize(text: str, limit: int = _EXCERPT) -> str:
    """Flatten whitespace and neutralize mermaid line-breaks."""
    flat = " ".join((text or "").split())
    flat = flat.replace(";", ",").replace(":", " -")
    return flat[:limit] + ("…" if len(flat) > limit else "")


def _step_lines(step, by_step: dict) -> List[str]:
    """Diagram lines for one step (plus a warning note on failure)."""
    idx = step.index
    if step.kind == TOOL_CALL:
        lines = [f"    A->>A: [{idx}] {_sanitize(step.tool or '')}"
                 f" {_sanitize(step.result)}"]
    else:
        note = step.thought or step.result or ""
        lines = ([f"    Note over A: [{idx}] {_sanitize(note)}"]
                 if note.strip() else [])
    if idx in by_step:
        det = by_step[idx]
        lines.append(f"    Note over A: ⚠ {det.mode_id} "
                     f"({_sanitize(det.evidence[0], 64)})")
    return lines


def render_mermaid(trace: Trace,
                   detections: Optional[List] = None) -> str:
    """The trace as a mermaid sequenceDiagram string."""
    by_step = {d.step_index: d for d in (detections or [])}
    lines = ["sequenceDiagram", "    participant U as User",
             "    participant A as Agent"]
    for step in trace.steps:
        lines.extend(_step_lines(step, by_step))
    if trace.final_output:
        lines.append(f"    A->>U: {_sanitize(trace.final_output)}")
    return "\n".join(lines) + "\n"
