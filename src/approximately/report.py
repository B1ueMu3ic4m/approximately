"""Self-contained HTML postmortem report (single file, no JS, no CDN)."""

from __future__ import annotations

import datetime
import html
import math
from typing import List, Optional, Sequence

from .attributor import FailureReport
from .taxonomy import CATEGORY_SHARE
from .trace import Trace

_CSS = """
:root { color-scheme: light; }
* { box-sizing: border-box; }
body { font: 15px/1.55 -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
       margin: 0; background: #f6f7f9; color: #1a1d21; }
main { max-width: 900px; margin: 0 auto; padding: 32px 20px 64px; }
.badge { display: inline-block; font-size: 11px; letter-spacing: .08em;
         text-transform: uppercase; padding: 3px 10px; border-radius: 999px;
         background: #e4e7eb; color: #495057; font-weight: 600; }
.badge.red { background: #fde8e8; color: #b02a37; }
.badge.green { background: #def7e5; color: #1c7430; }
h1 { font-size: 26px; margin: 14px 0 4px; }
.meta { color: #6c757d; font-size: 13px; margin-bottom: 24px; }
.card { background: #fff; border: 1px solid #e4e7eb; border-radius: 12px;
        padding: 20px 22px; margin-bottom: 18px; box-shadow: 0 1px 2px rgb(0 0 0 / 4%); }
.card h2 { margin: 0 0 8px; font-size: 15px; color: #495057;
           text-transform: uppercase; letter-spacing: .06em; }
.verdict-mode { font-size: 21px; font-weight: 700; }
.verdict-def { color: #495057; margin-top: 6px; }
.summary { border-left: 4px solid #b02a37; padding: 10px 14px; background: #fff5f5;
           border-radius: 0 8px 8px 0; margin-top: 10px; }
ul.evidence { margin: 8px 0 0; padding-left: 20px; }
ul.evidence li { margin: 4px 0; }
ol.fixes { margin: 8px 0 0; padding-left: 20px; }
ol.fixes li { margin: 6px 0; }
table.steps { width: 100%; border-collapse: collapse; font-size: 13px; }
table.steps th { text-align: left; color: #868e96; font-weight: 600; padding: 6px 8px;
                 border-bottom: 2px solid #e4e7eb; }
table.steps td { padding: 7px 8px; border-bottom: 1px solid #eef0f2; vertical-align: top; }
tr.hot td { background: #fff3bf66; }
tr.hot td:first-child { border-left: 3px solid #f08c00; }
.k { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px;
     color: #495057; }
.cat { display: flex; gap: 10px; align-items: center; margin: 6px 0; font-size: 13px; }
.cat .bar { height: 10px; border-radius: 5px; background: #b02a37; opacity: .75; }
footer { margin-top: 28px; color: #adb5bd; font-size: 12.5px; text-align: center; }
footer a { color: #748ffc; }
.disagree { background: #fff9db; border: 1px solid #ffe066; padding: 10px 14px;
            border-radius: 8px; margin-top: 10px; font-size: 13.5px; }
.spark-row { display: flex; gap: 14px; align-items: center; margin-top: 8px;
             flex-wrap: wrap; }
.spark-line { font-size: 12.5px; color: #6c757d; }
"""

TREND_LABELS = {
    "improving": ("green", "↓ failure rate falling"),
    "stable": ("", "→ flat"),
    "worsening": ("red", "↑ failure rate rising"),
}


def _finite(values: Sequence[float]) -> List[float]:
    """Coerce a series to plain floats, replacing non-finite with 0."""
    out: List[float] = []
    for v in values:
        try:
            f = float(v)
        except (TypeError, ValueError):
            f = 0.0
        out.append(f if math.isfinite(f) else 0.0)
    return out


def render_sparkline(values: Sequence[float], width: int = 220,
                     height: int = 40) -> str:
    """Inline-SVG sparkline — pure markup, no JS, no CDN."""
    vals = _finite(values)
    if not vals:
        vals = [0.0, 0.0]
    if len(vals) == 1:
        vals = vals + vals
    lo, hi = min(vals), max(vals)
    span = hi - lo
    n = len(vals)
    mid = height / 2
    if n == 1 or span <= 0 or not math.isfinite(span):
        # constant or overflowing range: flat midline
        points = [(width * i / (n - 1), mid) for i in range(n)]
    else:
        points = []
        for i, v in enumerate(vals):
            y = height - 3 - (v - lo) / span * (height - 6)
            points.append((width * i / (n - 1),
                           y if math.isfinite(y) else mid))
    pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
    last_x, last_y = points[-1]
    return (
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        f'role="img" aria-label="trend sparkline">'
        f'<polyline fill="none" stroke="#b02a37" stroke-width="2" '
        f'stroke-linejoin="round" points="{pts}"/>'
        f'<circle cx="{last_x:.1f}" cy="{last_y:.1f}" r="3" fill="#b02a37"/>'
        f"</svg>"
    )


def theil_sen_slope(values: Sequence[float]) -> float:
    """Robust trend slope: the median of all pairwise slopes.

    Theil-Sen rather than OLS — a single anomalous bucket (one bad deploy
    day) cannot drag the estimate the way least squares can. O(n²) is fine
    for the handful of buckets a report shows.
    """
    vals = _finite(values)
    n = len(vals)
    if n < 2:
        return 0.0
    slopes = [
        (vals[j] - vals[i]) / (j - i)
        for i in range(n) for j in range(i + 1, n)
    ]
    slopes.sort()
    m = len(slopes)
    mid = m // 2
    if m % 2:
        return slopes[mid]
    return (slopes[mid - 1] + slopes[mid]) / 2


def trend_verdict(values: Sequence[float],
                  threshold: float = 0.05) -> tuple:
    """Classify a failure-rate series as improving / stable / worsening.

    The slope is judged relative to the series' own mean level, so a
    2-point move on a 60% failure rate reads as noise while the same move
    on 5% reads as a real trend. Returns ``(verdict, slope)``.
    """
    vals = _finite(values)
    slope = theil_sen_slope(vals)
    mean = sum(vals) / len(vals) if vals else 0.0
    scale = mean if mean > 0.5 else 1.0  # absolute comparison near zero
    if slope <= -threshold * scale:
        return "improving", slope
    if slope >= threshold * scale:
        return "worsening", slope
    return "stable", slope


def _esc(text: str) -> str:
    return html.escape(str(text))


def _step_row(step, hot: set) -> str:
    detail = step.error or step.result or step.thought or ""
    detail = _esc(" ".join(detail.split())[:160])
    head = _esc(step.tool or "-")
    cls = ' class="hot"' if step.index in hot else ""
    return (
        f"<tr{cls}><td>#{step.index}</td><td class=\"k\">{step.kind}</td>"
        f"<td class=\"k\">{head}</td><td>{detail}</td>"
        f"<td class=\"k\">{step.latency_ms}ms</td></tr>"
    )


def _category_bars(primary_category: str) -> str:
    rows: List[str] = []
    for cat, share in CATEGORY_SHARE.items():
        active = cat == primary_category
        label = {  # short labels for the bar chart
            "FC1": "Specification & design",
            "FC2": "Inter-agent misalignment",
            "FC3": "Task verification",
        }[cat]
        width = share * 3  # px scale
        color = "#b02a37" if active else "#ced4da"
        suffix = " ← your failure" if active else ""
        rows.append(
            f'<div class="cat"><span style="width:190px">{_esc(label)}'
            f'{suffix}</span><span class="bar" style="width:{width}px;background:{color}">'
            f"</span><span class=\"k\">{share}%</span></div>"
        )
    return "".join(rows)


def _context_card(trace: Trace) -> str:
    """A small 'what would a half-size context forget?' card.

    Best-effort by design: any forecast failure yields an empty string
    rather than breaking the postmortem.
    """
    try:
        from .context import default_facts, forecast

        full = sum(
            (len(s.result or s.thought or "") // 4) + 8 for s in trace.steps
        ) + len(trace.task) // 4
        fc = forecast(trace, budget=max(1, full // 2),
                      facts=default_facts(trace))
        lost = ", ".join(fc.final_probe.lost) or "none"
        return (
            '<div class="card"><h2>Context Runtime · half-budget forecast</h2>'
            f'<p style="margin:4px 0">Budget <b>{fc.budget}</b> of '
            f"{fc.full_context_tokens} tokens → effective recall "
            f"<b>{fc.final_probe.recall:.0%}</b> · evictions {fc.evicted_count}"
            f' · lost facts: <b>{_esc(lost)}</b></p>'
            '<p style="margin:0;color:#6c757d;font-size:13px">Pin critical '
            "facts (runtime.pin) or raise the budget before this ships.</p>"
            "</div>"
        )
    except Exception:
        return ""


def _trend_card(trend_rows) -> str:
    """Sparkline + verdict for the failure-rate history (cluster.trend rows)."""
    try:
        rates = [float(r["failed"]) / r["total"]
                 for r in trend_rows if r.get("total")]
    except (KeyError, TypeError, ValueError, AttributeError):
        return ""
    if not rates:
        return ""
    verdict, slope = trend_verdict(rates)
    badge_cls, label = TREND_LABELS[verdict]
    start = trend_rows[0].get("bucket_start", "")
    end = trend_rows[-1].get("bucket_start", "")
    detail = (
        f"{len(trend_rows)} buckets · {start} → {end} · "
        f"slope {slope:+.3f}/bucket (Theil-Sen)"
    )
    return (
        '<div class="card"><h2>Failure-rate trend</h2>'
        '<div class="spark-row">'
        f"{render_sparkline([r * 100 for r in rates])}"
        f'<span class="badge {badge_cls}">{_esc(label)}</span>'
        f'<span class="spark-line">{_esc(detail)}</span>'
        "</div>"
        '<p style="margin:6px 0 0;color:#6c757d;font-size:13px">'
        "Failure rate per time bucket, oldest first. A rising line usually "
        "means a config or model change — bisect with replay tests.</p></div>"
    )


def render_index_html(items, trend_rows: Optional[list] = None) -> str:
    """Batch postmortem index: one row per (trace, report) pair.

    Pass ``trend_rows`` (from :func:`approximately.cluster.trend`) to add
    a failure-rate sparkline card with an improving/stable/worsening
    verdict.
    """
    rows = []
    for trace, rep in items:
        badge = "green" if not rep.failed else "red"
        status = "passed" if not rep.failed else rep.primary_mode.id
        created = datetime.datetime.fromtimestamp(
            trace.created_at or 0, datetime.timezone.utc
        ).strftime("%m-%d %H:%M")
        link = _esc(rep.trace_id) + ".report.html"
        rows.append(
            "<tr><td><a href=\"" + link + "\">" + _esc(rep.trace_id) + "</a></td>"
            + "<td>" + _esc(rep.task[:60]) + "</td>"
            + '<td><span class="badge ' + badge + '">' + _esc(status)
            + "</span></td>"
            + '<td class="k">' + str(len(trace.steps)) + " steps · "
            + created + "</td></tr>"
        )
    rows_html = "".join(rows) or '<tr><td colspan="4">no traces yet</td></tr>'
    trend_card = _trend_card(trend_rows) if trend_rows else ""
    return (
        '<!doctype html>\n<html><head><meta charset="utf-8">'
        "<title>approximately · postmortem index</title>\n"
        f"<style>{_CSS}</style></head><body><main>\n"
        "<h1>Postmortem index</h1>\n"
        f'<div class="meta">{len(items)} traces · generated by approximately</div>\n'
        f"{trend_card}"
        '<div class="card"><table class="steps">\n'
        "<tr><th>trace</th><th>task</th><th>verdict</th><th>meta</th></tr>\n"
        f"{rows_html}\n</table></div>\n"
        '<footer><a href="https://github.com/B1ueMu3ic4m/approximately">'
        "approximately</a></footer>\n</main></body></html>"
    )


def _evidence_cards(report: FailureReport) -> str:
    blocks = []
    for det in report.detections:
        primary = det.mode_id == report.primary_mode.id
        title = _esc(det.mode_id + (" (primary)" if primary else ""))
        blocks.append(
            f'<div class="card"><h2>Detection · {title}</h2>'
            f'<div class="k">{_esc(det.source)} · confidence {det.confidence:.2f} · {det.where}</div>'
            "<ul class=\"evidence\">"
            + "".join(f"<li>{_esc(e)}</li>" for e in det.evidence)
            + "</ul></div>"
        )
    return "".join(blocks)


def _disagreement_banner(report: FailureReport) -> str:
    if not report.disagreement:
        return ""
    return (f'<div class="disagree">⚠ Rule/judge disagreement: '
            f"{_esc(report.disagreement)}</div>")


def _fixes_card(report: FailureReport) -> str:
    if not report.suggested_fixes:
        return ""
    return ('<div class="card"><h2>Suggested Fixes</h2><ol class="fixes">'
            + "".join(f"<li>{_esc(f)}</li>" for f in report.suggested_fixes)
            + "</ol></div>")


def render_html(trace: Trace, report: FailureReport) -> str:
    hot = {d.step_index for d in report.detections}

    status = (
        '<span class="badge red">failed</span>'
        if report.failed
        else '<span class="badge green">passed</span>'
    )
    created = datetime.datetime.fromtimestamp(
        trace.created_at or 0, datetime.timezone.utc
    ).strftime("%Y-%m-%d %H:%M UTC")

    evidence_blocks = _evidence_cards(report)
    disagreement = _disagreement_banner(report)
    fixes = _fixes_card(report)
    steps_html = "".join(_step_row(s, hot) for s in trace.steps)
    context_card = _context_card(trace)

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Approximately report · {_esc(report.trace_id)}</title>
<style>{_CSS}</style></head>
<body><main>
<span class="badge">trace {_esc(report.trace_id)}</span> {status}
<h1>Postmortem: {_esc(report.task)}</h1>
<div class="meta">{_esc(trace.model)} · {len(trace.steps)} steps · {created} ·
generated by Approximately</div>

<div class="card">
  <h2>Verdict</h2>
  <div class="verdict-mode">{_esc(report.primary_mode.label)}</div>
  <div class="verdict-def">{_esc(report.primary_mode.definition)}</div>
  <div class="summary">{_esc(report.summary)}</div>
  {disagreement}
</div>

{evidence_blocks}
{fixes}
{context_card}

<div class="card">
  <h2>Where this mode sits in MAST</h2>
  <p style="margin:4px 0 10px;color:#6c757d;font-size:13px">
  Distribution of failure categories across 1600+ annotated agent trajectories
  (MAST, arXiv:2503.13657), with your primary mode's category highlighted:</p>
  {_category_bars(report.primary_mode.category)}
</div>

<div class="card">
  <h2>Recorded Timeline</h2>
  <table class="steps">
    <tr><th>#</th><th>kind</th><th>tool</th><th>detail</th><th>latency</th></tr>
    {steps_html}
  </table>
</div>

<footer>postmortem generated by
<a href="https://github.com/B1ueMu3ic4m/approximately">Approximately</a> —
the flight recorder for AI agents · taxonomy: MAST (arXiv:2503.13657)</footer>
</main></body></html>"""
