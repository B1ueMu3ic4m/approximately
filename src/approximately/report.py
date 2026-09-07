"""Self-contained HTML postmortem report (single file, no JS, no CDN)."""

from __future__ import annotations

import datetime
import html
from typing import List

from .attributor import FailureReport
from .taxonomy import CATEGORY_SHARE
from .trace import ERROR, RESPONSE, TOOL_CALL, Trace

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
"""


def _esc(text: str) -> str:
    return html.escape(str(text))


def _step_row(step) -> str:
    detail = step.error or step.result or step.thought or ""
    detail = _esc(" ".join(detail.split())[:160])
    head = _esc(step.tool or "-")
    cls = ' class="hot"' if step.meta.get("_hot") else ""
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


def render_html(trace: Trace, report: FailureReport) -> str:
    hot = {d.step_index for d in report.detections}
    for step in trace.steps:
        step.meta["_hot"] = step.index in hot

    status = (
        '<span class="badge red">failed</span>'
        if report.failed
        else '<span class="badge green">passed</span>'
    )
    created = datetime.datetime.fromtimestamp(
        trace.created_at or 0, datetime.timezone.utc
    ).strftime("%Y-%m-%d %H:%M UTC")

    evidence_blocks = []
    for det in report.detections:
        mode = report.primary_mode if det.mode_id == report.primary_mode.id else None
        title = _esc(det.mode_id + (" (primary)" if mode else ""))
        evidence_blocks.append(
            f'<div class="card"><h2>Detection · {title}</h2>'
            f'<div class="k">{_esc(det.source)} · confidence {det.confidence:.2f} · {det.where}</div>'
            "<ul class=\"evidence\">"
            + "".join(f"<li>{_esc(e)}</li>" for e in det.evidence)
            + "</ul></div>"
        )

    disagreement = (
        f'<div class="disagree">⚠ Rule/judge disagreement: {_esc(report.disagreement)}</div>'
        if report.disagreement
        else ""
    )

    fixes = (
        '<div class="card"><h2>Suggested Fixes</h2><ol class="fixes">'
        + "".join(f"<li>{_esc(f)}</li>" for f in report.suggested_fixes)
        + "</ol></div>"
        if report.suggested_fixes
        else ""
    )

    steps_html = "".join(_step_row(s) for s in trace.steps)

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
