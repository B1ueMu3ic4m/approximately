"""Token-cost vs recall/success curves (v0.3).

Two views over the same question — *what is my context budget buying me?*:

1. ``budget_curve(trace)`` — sweep budgets over one recorded run and compute
   effective recall + tokens for each (per-trace, deterministic, offline).
   This is the curve arXiv:2606.10209 measured per configuration; here it is
   per recording, over budgets instead of policies.
2. ``success_vs_tokens(traces)`` — scatter of run tokens vs success flag
   across a store: the empirical "did more context actually help?" view.

Output is a self-contained HTML file with inline SVG — no JS, no CDN.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, List, Optional, Tuple

from .context import default_facts, forecast, full_context_tokens
from .trace import Trace


@dataclass
class CurvePoint:
    budget: int
    tokens_used: int
    recall: float


@dataclass
class BudgetCurve:
    trace_id: str
    full_tokens: int
    points: List[CurvePoint] = field(default_factory=list)

    def to_svg_points(self, width: int, height: int, pad: int) -> str:
        max_budget = max((p.budget for p in self.points), default=1) or 1
        pts = []
        for p in self.points:
            x = pad + (p.budget / max_budget) * (width - 2 * pad)
            y = height - pad - p.recall * (height - 2 * pad)
            pts.append(f"{x:.1f},{y:.1f}")
        return " ".join(pts)


def budget_curve(trace: Trace, budgets: Optional[List[int]] = None,
                 steps: int = 8) -> BudgetCurve:
    """Sweep ``budgets`` (default: geometric grid over the run's full size)."""
    facts = default_facts(trace)
    full = full_context_tokens(trace)
    if budgets is None:
        budgets = sorted({
            max(1, int(full * f))
            for f in (0.15, 0.3, 0.5, 0.7, 0.85, 1.0, 1.5)
        })
    curve = BudgetCurve(trace_id=trace.id, full_tokens=full)
    for budget in budgets:
        fc = forecast(trace, budget=budget, facts=facts)
        curve.points.append(CurvePoint(
            budget=budget,
            tokens_used=fc.budgeted_tokens,
            recall=fc.final_recall,
        ))
    return curve





def success_vs_tokens(traces: Iterable[Trace]) -> List[Tuple[int, Optional[bool]]]:
    """(tokens, success) per trace for the cross-run scatter."""

    out = []
    for trace in traces:
        tokens = full_context_tokens(trace)
        for step in trace.steps:  # count llm-side cost too, if recorded
            tokens += step.tokens
        out.append((tokens, trace.success))
    return out


def _svg_line(points: List[Tuple[float, float]], width: int, height: int,
              pad: int, color: str) -> str:
    if not points:
        return ""
    max_x = max(x for x, _ in points) or 1
    min_x = min(x for x, _ in points)
    span_x = (max_x - min_x) or 1
    coords = " ".join(
        f"{pad + (x - min_x) / span_x * (width - 2 * pad):.1f},"
        f"{height - pad - y * (height - 2 * pad):.1f}"
        for x, y in points
    )
    return (f'<polyline fill="none" stroke="{color}" stroke-width="2.5" '
            f'points="{coords}" />')


def render_curve_html(curve: BudgetCurve,
                      scatter: Optional[List[Tuple[int, Optional[bool]]]] = None
                      ) -> str:
    """Self-contained HTML: budget-vs-recall line (+ optional scatter)."""
    width, height, pad = 640, 300, 40
    line = _svg_line([(p.budget, p.recall) for p in curve.points],
                     width, height, pad, "#b02a37")
    dots = " ".join(
        f'<circle cx="{pad + (p.budget / max(p.budget for p in curve.points) or 1) * (width - 2 * pad):.1f}" '
        f'cy="{height - pad - p.recall * (height - 2 * pad):.1f}" r="4" fill="#1a1d21" />'
        f'<text x="{pad + (p.budget / max(p.budget for p in curve.points) or 1) * (width - 2 * pad):.1f}" '
        f'y="{height - pad - p.recall * (height - 2 * pad):.1f}" '
        f'dx="7" dy="-6" font-size="10" fill="#495057">{p.budget}tok / {p.recall:.0%}</text>'
        for p in curve.points
    )
    scatter_svg = ""
    if scatter:
        max_tokens = max((t for t, _ in scatter), default=1) or 1
        marks = []
        for tokens, success in scatter:
            x = pad + tokens / max_tokens * (width - 2 * pad)
            color = "#1c7430" if success else "#b02a37"
            marks.append(
                f'<circle cx="{x:.1f}" cy="{height - pad - (height - 2 * pad) / 2:.1f}" '
                f'r="4" fill="{color}" opacity="0.8" />'
            )
        scatter_svg = (
            f"<p>Runs by token cost (green = success, red = failure):</p>"
            f'<svg viewBox="0 0 {width} {height}" width="{width}" '
            f'height="{height}"><rect width="{width}" height="{height}" '
            f'fill="#f6f7f9" />{"".join(marks)}</svg>'
        )
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>approximately · cost/recall curve</title>
<style>body{{font:15px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;max-width:760px;
margin:32px auto;padding:0 16px;color:#1a1d21}} .card{{background:#fff;border:1px solid #e4e7eb;
border-radius:12px;padding:18px;margin-bottom:16px}} code{{background:#f1f3f5;padding:2px 6px;
border-radius:4px}} footer{{color:#adb5bd;font-size:12.5px;text-align:center}}</style></head>
<body><h1>Context budget vs effective recall</h1>
<div class="card">
<p>Trace <code>{curve.trace_id}</code> — full context {curve.full_tokens} tokens.
Recall is measured with the probe facts of this recording.</p>
<svg viewBox="0 0 {width} {height}" width="{width}" height="{height}">
<rect width="{width}" height="{height}" fill="#f6f7f9" />
<line x1="{pad}" y1="{height - pad}" x2="{width - pad}" y2="{height - pad}" stroke="#ced4da" />
<line x1="{pad}" y1="{pad}" x2="{pad}" y2="{height - pad}" stroke="#ced4da" />
{line}{dots}
</svg></div>
{scatter_svg}
<footer>generated by <a href="https://github.com/B1ueMu3ic4m/approximately">approximately</a>
· context runtime · curve over {len(curve.points)} budgets</footer>
</body></html>"""
