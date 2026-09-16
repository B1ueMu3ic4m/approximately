"""Fleet dashboard: aggregate several trace stores into one HTML page.

Multi-team reality: every laptop, CI runner and environment has its own
store. `survey` walks any number of store directories and computes the
same health numbers per store — trace count, failure rate, trend,
top failure modes — plus fleet-wide totals, and
`render_fleet_html` lays them out as one self-contained page (no JS,
no CDN, same visual language as the postmortem reports).

Store names come from directory paths (untrusted input for HTML), so
everything user-controlled is escaped before it touches markup.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from .attributor import attribute
from .cluster import trend
from .ledger import verify_ledger
from .report import TREND_LABELS, render_sparkline, trend_verdict
from .store import TraceStore

_FLEET_CSS = """
body { font: 15px/1.55 -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
       margin: 0; background: #f6f7f9; color: #1a1d21; }
main { max-width: 980px; margin: 0 auto; padding: 32px 20px 64px; }
h1 { font-size: 24px; margin: 0 0 4px; }
.meta { color: #6c757d; font-size: 13px; margin-bottom: 22px; }
.kpis { display: flex; gap: 14px; flex-wrap: wrap; margin-bottom: 18px; }
.kpi { background: #fff; border: 1px solid #e4e7eb; border-radius: 12px;
       padding: 14px 20px; min-width: 150px; }
.kpi .num { font-size: 26px; font-weight: 700; }
.kpi .cap { color: #868e96; font-size: 12px; text-transform: uppercase;
            letter-spacing: .06em; }
.store { background: #fff; border: 1px solid #e4e7eb; border-radius: 12px;
         padding: 16px 20px; margin-bottom: 14px; }
.store h2 { margin: 0; font-size: 16px; }
.store .sub { color: #6c757d; font-size: 12.5px; margin: 2px 0 10px; }
.row { display: flex; gap: 18px; align-items: center; flex-wrap: wrap; }
.rate { font-size: 20px; font-weight: 700; }
.rate.ok { color: #1c7430; } .rate.bad { color: #b02a37; }
table { border-collapse: collapse; font-size: 13px; margin-top: 8px; }
td { padding: 3px 12px 3px 0; border-bottom: 1px solid #eef0f2; }
.mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
footer { margin-top: 22px; color: #adb5bd; font-size: 12.5px; text-align: center; }
.badge { display: inline-block; font-size: 11px; letter-spacing: .08em;
         text-transform: uppercase; padding: 3px 10px; border-radius: 999px;
         background: #e4e7eb; color: #495057; font-weight: 600; }
.badge.red { background: #fde8e8; color: #b02a37; }
.badge.green { background: #def7e5; color: #1c7430; }
"""


@dataclass
class StoreSummary:
    name: str
    path: str
    traces: int = 0
    failed: int = 0
    failure_rate: float = 0.0
    top_modes: List[tuple] = field(default_factory=list)
    trend_rows: List[dict] = field(default_factory=list)
    ledger_intact: Optional[bool] = None  # None: no ledger in use
    trend_verdict: str = "stable"
    trend_slope: float = 0.0

    @property
    def worsening(self) -> bool:
        return self.trend_verdict == "worsening"


def _verdict(trend_rows: List[dict]) -> tuple:
    """Theil-Sen verdict over the store's failure-rate history."""
    rates = [r["failed"] / r["total"] for r in trend_rows if r.get("total")]
    return trend_verdict(rates)


def _top_failure_modes(traces) -> List[tuple]:
    """Attribute every non-success trace with the rule detectors only."""
    modes: dict = {}
    for t in traces:
        if t.success is True:
            continue
        rep = attribute(t)
        if rep.failed and rep.primary_mode.id != "OTHER":
            modes[rep.primary_mode.id] = modes.get(rep.primary_mode.id, 0) + 1
    return sorted(modes.items(), key=lambda kv: -kv[1])[:3]


def _ledger_state(directory: Path) -> Optional[bool]:
    if not (directory / "ledger.jsonl").is_file():
        return None
    return verify_ledger(directory).intact


def webhook_payload(summaries: List[StoreSummary]) -> dict:
    """JSON-serializable fleet summary for a notification endpoint."""
    return {
        "generated_at": datetime.datetime.now(
            datetime.timezone.utc).isoformat(timespec="seconds"),
        "stores": [
            {
                "name": s.name,
                "path": s.path,
                "traces": s.traces,
                "failure_rate": round(s.failure_rate, 4),
                "trend_verdict": s.trend_verdict,
                "trend_slope": round(s.trend_slope, 4),
                "worsening": s.worsening,
                "ledger_intact": s.ledger_intact,
                "top_modes": [
                    {"mode": mode, "count": count}
                    for mode, count in s.top_modes
                ],
            }
            for s in summaries
        ],
        "worsening_stores": [s.name for s in summaries if s.worsening],
    }


def notify_webhook(summaries: List[StoreSummary], url: str,
                   signing_key: Optional[bytes] = None,
                   timeout: float = 10.0) -> str:
    """POST the fleet summary as JSON; returns the response status.

    When a signing key is configured (APPROXIMATELY_SIGNING_KEY), the
    body is HMAC-signed and the hex digest travels in the
    ``X-Approximately-Signature`` header, so a receiver can authenticate
    the alert the same way the evidence chain authenticates traces.
    Transport errors raise - the caller decides whether notification
    failure is fatal for their pipeline.
    """
    import hashlib
    import hmac as _hmac
    import json as _json
    import urllib.error
    import urllib.request

    body = _json.dumps(webhook_payload(summaries),
                       sort_keys=True).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if signing_key:
        digest = _hmac.new(signing_key, body, hashlib.sha256).hexdigest()
        headers["X-Approximately-Signature"] = f"sha256={digest}"
    request = urllib.request.Request(url, data=body, headers=headers,
                                     method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return f"{response.status}"
    except urllib.error.HTTPError as exc:
        return f"HTTP {exc.code}"
    except (urllib.error.URLError, OSError) as exc:
        raise RuntimeError(f"webhook delivery failed: {exc}") from exc


def survey(stores: List[Path]) -> List[StoreSummary]:
    """Compute fleet health numbers for each store directory.

    Attribution runs on the rule detectors only — a fleet sweep must
    not need an API key or make network calls.
    """
    summaries: List[StoreSummary] = []
    for path in stores:
        store = TraceStore(Path(path))
        traces = store.list_traces()
        failed = sum(1 for t in traces if t.success is False)
        rows = trend(traces)
        verdict, slope = _verdict(rows)
        summaries.append(StoreSummary(
            name=Path(path).name or str(path),
            path=str(path),
            traces=len(traces),
            failed=failed,
            failure_rate=failed / len(traces) if traces else 0.0,
            top_modes=_top_failure_modes(traces),
            trend_rows=rows,
            ledger_intact=_ledger_state(store.directory),
            trend_verdict=verdict,
            trend_slope=slope,
        ))
    return summaries


def _store_card(s: StoreSummary) -> str:
    """One store's card: rate, trend sparkline + verdict, top modes."""
    import html as _html

    esc = _html.escape
    rate_cls = "bad" if s.failure_rate >= 0.5 else "ok"
    rates = [r["failed"] / r["total"] * 100 for r in s.trend_rows
             if r.get("total")]
    spark = render_sparkline(rates, width=180, height=34) if rates else ""
    badge_cls, trend_label = TREND_LABELS[s.trend_verdict]
    ledger_note = {True: "ledger intact",
                   False: "<b>LEDGER BROKEN</b>",
                   None: "no ledger"}[s.ledger_intact]
    modes_html = "".join(
        f"<tr><td class='mono'>{esc(mode)}</td><td>{count}</td></tr>"
        for mode, count in s.top_modes
    ) or "<tr><td>no attributed failures</td></tr>"
    return (
        f'<div class="store"><h2>{esc(s.name)}</h2>'
        f'<div class="sub">{esc(s.path)} · '
        f'{s.traces} traces · ledger: {ledger_note}</div>'
        '<div class="row">'
        f'<span class="rate {rate_cls}">{s.failure_rate:.0%}</span>'
        f"{spark}"
        f'<span class="badge {badge_cls}">{esc(trend_label)}</span>'
        "</div>"
        f"<table>{modes_html}</table></div>"
    )


def render_fleet_html(summaries: List[StoreSummary]) -> str:
    """Self-contained fleet dashboard page."""
    import datetime

    total = sum(s.traces for s in summaries)
    failed = sum(s.failed for s in summaries)
    rate = failed / total if total else 0.0

    cards_html = "".join(_store_card(s) for s in summaries) \
        or "<p>No stores surveyed.</p>"
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>approximately · fleet dashboard</title>
<style>{_FLEET_CSS}</style></head><body><main>
<h1>Fleet dashboard</h1>
<div class="meta">{len(summaries)} stores · {total} traces ·
generated {datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}
by approximately</div>
<div class="kpis">
  <div class="kpi"><div class="num">{total}</div>
    <div class="cap">traces</div></div>
  <div class="kpi"><div class="num">{rate:.1%}</div>
    <div class="cap">fleet failure rate</div></div>
  <div class="kpi"><div class="num">{sum(1 for s in summaries if s.ledger_intact is False)}</div>
    <div class="cap">broken ledgers</div></div>
</div>
{cards_html}
<footer>generated by
<a href="https://github.com/B1ueMu3ic4m/approximately">approximately</a>
· taxonomy: MAST (arXiv:2503.13657)</footer>
</main></body></html>"""
