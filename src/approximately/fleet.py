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
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from .attributor import attribute
from .cluster import UNATTRIBUTED, agent_scorecard, trend
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
    top_agents: List[dict] = field(default_factory=list)
    trend_rows: List[dict] = field(default_factory=list)
    ledger_intact: Optional[bool] = None  # None: no ledger in use
    trend_verdict: str = "stable"
    trend_slope: float = 0.0
    annotations: int = 0
    fleet_anomalies: int = 0
    worst_anomaly: Optional[dict] = None
    token_anomalies: int = 0
    worst_token_anomaly: Optional[dict] = None
    annotations_confirmed: int = 0
    total_tokens: int = 0
    est_spend: Optional[float] = None
    spend_unpriced_tokens: int = 0
    budget_breaches: int = 0
    breached_agents: List[str] = field(default_factory=list)

    @property
    def worsening(self) -> bool:
        return self.trend_verdict == "worsening"


def _breached_agents(traces: list) -> List[str]:
    """Agents named by per-agent ceilings as breached, in stamp order."""
    names: List[str] = []
    for t in traces:
        if not isinstance(t.meta, dict):
            continue
        agents = t.meta.get("budget", {}).get("agents") \
            if isinstance(t.meta.get("budget"), dict) else None
        if isinstance(agents, dict):
            for name, st in agents.items():
                if isinstance(st, dict) and \
                        st.get("exceeded") is True and \
                        name not in names:
                    names.append(name)
    return names


def _budget_breaches(traces: list) -> int:
    """Runs the live Budget rails stamped as breached.

    A thin count over store.stamped_breach — the single predicate
    every surface shares (fleet card, webhook payload, alert
    reasons, the ci gate's ``--max-budget-breaches``)."""
    from .store import stamped_breach

    return sum(1 for t in traces if stamped_breach(t.meta))


def _verdict(trend_rows: List[dict]) -> tuple:
    """Theil-Sen verdict over the store's failure-rate history."""
    rates = [r["failed"] / r["total"] for r in trend_rows if r.get("total")]
    return trend_verdict(rates)


def _top_agents(traces: list, n: int = 3) -> List[dict]:
    """Busiest named agents across the store (scorecard order)."""
    return [r for r in agent_scorecard(traces)
            if r["agent"] != UNATTRIBUTED][:n]


def _top_failure_modes(traces: list) -> List[tuple]:
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
                "failures": s.failed,
                "failure_rate": round(s.failure_rate, 4),
                "trend_verdict": s.trend_verdict,
                "trend_slope": round(s.trend_slope, 4),
                "worsening": s.worsening,
                "ledger_intact": s.ledger_intact,
                "annotations": getattr(s, "annotations", 0),
                "annotations_confirmed":
                    getattr(s, "annotations_confirmed", 0),
                "fleet_anomalies": getattr(s, "fleet_anomalies", 0),
                "worst_anomaly": getattr(s, "worst_anomaly", None),
                "token_anomalies": getattr(s, "token_anomalies", 0),
                "worst_token_anomaly":
                    getattr(s, "worst_token_anomaly", None),
                "total_tokens": getattr(s, "total_tokens", 0),
                "est_spend": getattr(s, "est_spend", None),
                "spend_unpriced_tokens":
                    getattr(s, "spend_unpriced_tokens", 0),
                "budget_breaches": getattr(s, "budget_breaches", 0),
                "breached_agents": getattr(s, "breached_agents", []),
                "top_modes": [
                    {"mode": mode, "count": count}
                    for mode, count in s.top_modes
                ],
                "top_agents": [
                    {k: r.get(k) for k in ("agent", "steps",
                                           "tool_calls", "errors",
                                           "tokens", "failed_traces",
                                           "failure_rate", "p95_ms",
                                           "breached_traces")}
                    for r in s.top_agents
                ],
            }
            for s in summaries
        ],
        "worsening_stores": [s.name for s in summaries if s.worsening],
    }


def notify_webhook(summaries: List[StoreSummary], url: str,
                   signing_key: Optional[bytes] = None,
                   timeout: float = 10.0,
                   payload: Optional[dict] = None,
                   attempts: int = 3) -> str:
    """POST the fleet summary as JSON; returns the response status.

    ``payload`` replaces the derived body (the spool watch posts its
    own pass result through the same signed channel).  When a
    signing key is configured (APPROXIMATELY_SIGNING_KEY), the body
    is HMAC-signed and the hex digest travels in the
    ``X-Approximately-Signature`` header, so a receiver can authenticate
    the alert the same way the evidence chain authenticates traces.

    Transient failures are retried with bounded exponential backoff
    (0.5s, 1s, 2s): connection errors, and definite-but-busy answers
    (5xx and 429, which honors a bounded Retry-After).  Any other
    4xx is a definite answer — retrying would just re-announce the
    same summary.  Exhausting the attempts raises.
    """
    import hashlib
    import hmac
    import json as _json

    scheme = urllib.parse.urlparse(url).scheme.lower()
    if scheme not in ("http", "https"):
        # also blocks file:// and custom schemes from sneaking in
        # through configuration
        raise RuntimeError(f"webhook URL must be http(s), got {scheme!r}")

    body = _json.dumps(payload if payload is not None
                       else webhook_payload(summaries),
                       sort_keys=True).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if signing_key:
        digest = hmac.new(signing_key, body, hashlib.sha256).hexdigest()
        headers["X-Approximately-Signature"] = f"sha256={digest}"
    attempts = max(1, int(attempts))
    last_error: Exception = RuntimeError("no attempt made")
    for attempt in range(1, attempts + 1):
        # a fresh Request per attempt: urllib handlers may consume
        # the payload, and a reused one has resent as garbage before
        request = urllib.request.Request(url, data=body,
                                         headers=headers, method="POST")
        try:
            with urllib.request.urlopen(  # nosec B310: scheme checked above
                    request, timeout=timeout) as response:
                return f"{response.status}"
        except urllib.error.HTTPError as exc:
            if exc.code == 429 or exc.code >= 500:
                last_error = RuntimeError(f"HTTP {exc.code}")
                if attempt < attempts:
                    time.sleep(_retry_delay(exc, attempt))
                continue
            return f"HTTP {exc.code}"
        except (urllib.error.URLError, OSError) as exc:
            last_error = exc
            if attempt < attempts:
                time.sleep(min(4.0, 0.5 * 2 ** (attempt - 1)))
    raise RuntimeError(
        f"webhook delivery failed after {attempts} attempts: "
        f"{last_error}") from last_error


def _retry_delay(exc: "urllib.error.HTTPError", attempt: int) -> float:
    """Bounded exponential backoff; a 429's Retry-After wins when it
    parses, capped at 5s so a hostile header cannot stall a watch."""
    base = min(4.0, 0.5 * 2 ** (attempt - 1))
    if exc.code == 429 and exc.headers is not None:
        raw = exc.headers.get("Retry-After")
        if raw is not None:
            try:
                return min(5.0, max(0.0, float(raw)))
            except ValueError:
                return base
    return base


def survey(stores: List[Path], top_agents: int = 3,
           prices: Optional[dict] = None) -> List[StoreSummary]:
    """Compute fleet health numbers for each store directory.

    Attribution runs on the rule detectors only — a fleet sweep must
    not need an API key or make network calls. ``top_agents`` sizes
    the per-store busiest-agents snapshot (digest snapshots inherit
    it, and ``fleet --trend --agent`` can only see agents inside
    it).
    """
    summaries: List[StoreSummary] = []
    for path in stores:
        store = TraceStore(Path(path))
        traces = store.list_traces()
        failed = sum(1 for t in traces if t.success is False)
        total_tokens = sum(step.tokens for t in traces
                           for step in t.steps)
        rows = trend(traces)
        verdict, slope = _verdict(rows)
        health = store.annotations_health()
        notes = store.annotations()
        from .anomaly import detect_fleet_anomalies, detect_fleet_token_anomalies

        anomalies = detect_fleet_anomalies(traces)
        token_flags = detect_fleet_token_anomalies(traces)
        summaries.append(StoreSummary(
            name=Path(path).name or str(path),
            path=str(path),
            traces=len(traces),
            failed=failed,
            failure_rate=failed / len(traces) if traces else 0.0,
            top_modes=_top_failure_modes(traces),
            top_agents=_top_agents(traces, top_agents),
            trend_rows=rows,
            ledger_intact=_ledger_state(store.directory),
            trend_verdict=verdict,
            trend_slope=slope,
            annotations=health["total"],
            annotations_confirmed=sum(
                1 for a in notes if a.get("verdict") == "confirmed"),
            fleet_anomalies=len(anomalies),
            worst_anomaly=None if not anomalies else {
                "trace_id": anomalies[0].trace_id,
                "tool": anomalies[0].tool,
                "latency_ms": anomalies[0].latency_ms,
                "median_ms": anomalies[0].median_ms,
                "robust_z": anomalies[0].robust_z,
            },
            token_anomalies=len(token_flags),
            worst_token_anomaly=None if not token_flags else {
                "trace_id": token_flags[0].trace_id,
                "tool": token_flags[0].tool,
                "tokens": token_flags[0].tokens,
                "median_tokens": token_flags[0].median_tokens,
                "robust_z": token_flags[0].robust_z,
            },
            total_tokens=total_tokens,
            budget_breaches=_budget_breaches(traces),
            breached_agents=_breached_agents(traces),
            **_spend(traces, total_tokens, prices),
        ))
    return summaries


def _spend(traces: list, total_tokens: int,
           prices: Optional[dict]) -> dict:
    """Per-store spend when a prices table is in play (blended $/1k
    per trace model); unpriced tokens are counted, never silently
    free.  Without a table: the token count alone."""
    if not prices:
        return {"est_spend": None, "spend_unpriced_tokens": 0}
    spend = 0.0
    unpriced = 0
    for trace in traces:
        rate = prices.get(str(trace.model or "unknown"))
        tokens = sum(step.tokens for step in trace.steps)
        if rate is None:
            unpriced += tokens
        else:
            spend += tokens / 1000 * rate
    return {"est_spend": round(spend, 4),
            "spend_unpriced_tokens": unpriced if unpriced
            or total_tokens else 0}


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
    agents_html = "".join(
        "<tr><td class='mono'>" + esc(r["agent"]) + "</td>"
        f"<td>{r['steps']}</td><td>{r['tokens']:,}</td>"
        f"<td>{r['errors']}</td>"
        f"<td>{r['failure_rate']:.0%}</td>"
        "<td>" + (f"{r['p95_ms']:.0f}ms" if r.get("p95_ms")
                  is not None else "-") + "</td></tr>"
        for r in s.top_agents
    ) or "<tr><td>no named agents recorded</td></tr>"
    anomalies = getattr(s, "fleet_anomalies", 0) or 0
    worst = getattr(s, "worst_anomaly", None)
    anomaly_html = ""
    if anomalies and worst:
        slow_cls = "bad" if anomalies >= 3 else "ok"
        anomaly_html = (
            f'<div class="row"><span class="rate {slow_cls}">'
            f'{anomalies}</span><span class="badge {slow_cls}">'
            "slow outlier(s)</span></div>"
            "<h3>Slowest step</h3><table>"
            f"<tr><td class='mono'>{esc(worst['tool'])}</td>"
            f"<td>{worst['latency_ms']}ms</td>"
            f"<td>family median {worst['median_ms']:.0f}ms · "
            f"z={worst['robust_z']}</td></tr></table>")
    token_flags = getattr(s, "token_anomalies", 0) or 0
    worst_tok = getattr(s, "worst_token_anomaly", None)
    if token_flags and worst_tok:
        tok_cls = "bad" if token_flags >= 3 else "ok"
        anomaly_html += (
            f'<div class="row"><span class="rate {tok_cls}">'
            f'{token_flags}</span><span class="badge {tok_cls}">'
            "token burn(s)</span></div>"
            "<h3>Hardest-working step</h3><table>"
            f"<tr><td class='mono'>{esc(worst_tok['tool'])}</td>"
            f"<td>{worst_tok['tokens']} tok</td>"
            f"<td>family median {worst_tok['median_tokens']:.0f} · "
            f"z={worst_tok['robust_z']}</td></tr></table>")
    anomaly_html += _breach_html(s)
    sub = (f'{esc(s.path)} · {s.traces} traces · ledger: '
           f'{ledger_note} · notes: {getattr(s, "annotations", 0)} '
           f'({getattr(s, "annotations_confirmed", 0)} confirmed)')
    if getattr(s, "total_tokens", 0):
        sub += f' · {s.total_tokens:,} tokens'
        if getattr(s, "est_spend", None) is not None:
            sub += f' · est ${s.est_spend:,.2f}'
    return (
        f'<div class="store"><h2>{esc(s.name)}</h2>'
        f'<div class="sub">{sub}</div>'
        '<div class="row">'
        f'<span class="rate {rate_cls}">{s.failure_rate:.0%}</span>'
        f"{spark}"
        f'<span class="badge {badge_cls}">{esc(trend_label)}</span>'
        "</div>"
        + anomaly_html +
        "<h3>Top failure modes</h3>"
        f"<table>{modes_html}</table>"
        "<h3>Busiest agents</h3>"
        "<table>"
        "<tr><th>agent</th><th>steps</th><th>tokens</th><th>errors</th>"
        "<th>fail-rate</th><th>p95</th></tr>"
        + agents_html + "</table></div>"
    )


def _breach_html(s: StoreSummary) -> str:
    """The budget-breach card row — empty when the store is clean."""
    breaches = getattr(s, "budget_breaches", 0) or 0
    if not breaches:
        return ""
    import html as _html

    agents = [a for a in getattr(s, "breached_agents", [])
              if isinstance(a, str)]
    who = (f" — agents: {_html.escape(', '.join(agents))}"
           if agents else "")
    return ('<div class="row"><span class="rate bad">'
            f'{breaches}</span><span class="badge bad">'
            "budget breach(es) — the live rails stopped these "
            f"runs{who}</span></div>")


def _trend_section(summary: dict) -> str:
    """HTML block for the digest-history trend (render_fleet_html)."""
    import html as _html

    esc = _html.escape
    # day rows carry `traces`/`failure_rate` (trace-weighted across
    # stores) — a r.get("total") read here matched nothing, so the
    # rate curve silently never rendered
    rates = [r["failure_rate"] * 100 for r in summary["days"]
             if r.get("traces")]
    spark = render_sparkline(rates, width=420, height=70) if rates \
        else "<p>(no snapshots with traces yet)</p>"
    badge_cls, trend_label = TREND_LABELS[summary["verdict"]]
    anomaly_trend = summary.get("anomaly_trend")
    token_trend = summary.get("token_trend")
    breach_trend = summary.get("breach_trend")
    if anomaly_trend or token_trend or breach_trend:
        rows = (f"<tr><td>{esc(r['day'])}</td>"
                f"<td>{r['traces']}</td>"
                f"<td>{r.get('fleet_anomalies', 0)}</td>"
                f"<td>{r.get('token_anomalies', 0)}</td>"
                f"<td>{r.get('budget_breaches', 0)}</td>"
                f"<td>{r['failure_rate']:.0%}</td></tr>"
                for r in summary["days"])
        trend_bits = [('<div class="row">'
                       f'<span class="badge {badge_cls}">'
                       f'{esc(trend_label)}</span>'
                       '<span class="sub">slope '
                       f'{summary["slope"]:+.4f}/day · '
                       f'{summary["snapshots"]} snapshot(s) over '
                       f'{len(summary["days"])} day(s)</span></div>'),
                      spark]
        if anomaly_trend:
            a_cls, a_label = TREND_LABELS[anomaly_trend["verdict"]]
            trend_bits.append(
                '<div class="row"><span class="badge ' + a_cls + '">'
                f'{esc(a_label)}</span>'
                '<span class="sub">slowness: latest '
                f'{anomaly_trend["latest"]} flagged step(s), slope '
                f'{anomaly_trend["slope"]:+.4f}/day</span></div>')
            trend_bits.append('<div class="row">'
                              + render_sparkline(
                                  [r["fleet_anomalies"]
                                   for r in summary["days"]],
                                  width=420, height=40)
                              + "</div>")
        if token_trend:
            t_cls, t_label = TREND_LABELS[token_trend["verdict"]]
            trend_bits.append(
                '<div class="row"><span class="badge ' + t_cls + '">'
                f'{esc(t_label)}</span>'
                '<span class="sub">token burn: latest '
                f'{token_trend["latest"]} flagged step(s), slope '
                f'{token_trend["slope"]:+.4f}/day</span></div>')
            trend_bits.append('<div class="row">'
                              + render_sparkline(
                                  [r["token_anomalies"]
                                   for r in summary["days"]],
                                  width=420, height=40)
                              + "</div>")
        breach_trend = summary.get("breach_trend")
        if breach_trend:
            b_cls, b_label = TREND_LABELS[breach_trend["verdict"]]
            trend_bits.append(
                '<div class="row"><span class="badge ' + b_cls + '">'
                f'{esc(b_label)}</span>'
                '<span class="sub">budget breaches: latest '
                f'{breach_trend["latest"]}, slope '
                f'{breach_trend["slope"]:+.4f}/day</span></div>')
            trend_bits.append('<div class="row">'
                              + render_sparkline(
                                  [r.get("budget_breaches", 0)
                                   for r in summary["days"]],
                                  width=420, height=40)
                              + "</div>")
        spend_trend = summary.get("spend_trend")
        if spend_trend:
            s_cls, s_label = TREND_LABELS[spend_trend["verdict"]]
            trend_bits.append(
                '<div class="row"><span class="badge ' + s_cls + '">'
                f'{esc(s_label)}</span>'
                '<span class="sub">spend: latest '
                f'${spend_trend["latest"]:,.2f}, slope '
                f'${spend_trend["slope"]:+.2f}/day</span></div>')
            trend_bits.append('<div class="row">'
                              + render_sparkline(
                                  [r.get("est_spend") or 0.0
                                   for r in summary["days"]],
                                  width=420, height=40)
                              + "</div>")
        return (
            '<div class="store"><h2>Fleet trend (digest history)</h2>'
            + "".join(trend_bits) +
            "<table><tr><th>day</th><th>traces</th>"
            "<th>slow outliers</th><th>token burn</th>"
            "<th>budget breaches</th>"
            "<th>failure rate</th></tr>"
            + "".join(rows) + "</table></div>")
    rows_html = "".join(
        f"<tr><td>{esc(r['day'])}</td>"
        f"<td>{r['traces']}</td>"
        f"<td>{r['failure_rate']:.0%}</td></tr>"
        for r in summary["days"])
    return (
        '<div class="store"><h2>Fleet trend (digest history)</h2>'
        f'<div class="row"><span class="badge {badge_cls}">'
        f'{esc(trend_label)}</span>'
        f'<span class="sub">slope {summary["slope"]:+.4f}/day · '
        f'{summary["snapshots"]} snapshot(s) over '
        f'{len(summary["days"])} day(s)</span></div>'
        f"{spark}"
        f"<table><tr><th>day</th><th>traces</th>"
        "<th>failure rate</th></tr>" + rows_html + "</table></div>")


def render_fleet_html(summaries: List[StoreSummary],
                      trend_summary: Optional[dict] = None) -> str:
    """Self-contained fleet dashboard page. With ``trend_summary``
    (summarize_trend over a digest dir), the day-level fleet trend
    section is embedded above the store cards."""
    import datetime

    total = sum(s.traces for s in summaries)
    failed = sum(s.failed for s in summaries)
    rate = failed / total if total else 0.0

    cards_html = "".join(_store_card(s) for s in summaries) \
        or "<p>No stores surveyed.</p>"
    trend_html = _trend_section(trend_summary) \
        if trend_summary else ""
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
{trend_html}
{cards_html}
<footer>generated by
<a href="https://github.com/B1ueMu3ic4m/approximately">approximately</a>
· taxonomy: MAST (arXiv:2503.13657)</footer>
</main></body></html>"""


def digest_snapshot(summaries: List[StoreSummary]) -> dict:
    """One JSONL line for the watch loop: fleet state at a timestamp."""
    return {
        "ts": time.time(),
        "stores": webhook_payload(summaries)["stores"],
        "worsening": [s.name for s in summaries if s.worsening],
    }


def append_digest(digest_dir: Path, snapshot: dict) -> Path:
    """Append one snapshot line to the current day's JSONL file."""
    digest_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d")
    path = digest_dir / f"digest-{stamp}.jsonl"
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(snapshot, sort_keys=True) + "\n")
    return path


def compact_digests(digest_dir: Path, dry_run: bool = False
                    ) -> Dict[str, Any]:
    """Collapse each day's snapshot history to its last line.

    A watch appends every cycle; a fleet running at a 10s interval
    writes 8,640 lines per day, and the trend reader only ever
    looks at the LAST snapshot per day (trend_days).  Compaction
    keeps exactly what the trend reads — the day's final state and
    its snapshot count — and rewrites each day file in place.
    Today's file is included: the compacted form is what append
    continues from.  Returns per-file line counts.
    """
    report: Dict[str, Any] = {"files": [], "before": 0, "after": 0}
    for path in sorted(digest_dir.glob("digest-*.jsonl")):
        lines = [line for line in path.read_text(
            encoding="utf-8").splitlines() if line.strip()]
        last = None
        snapshots = 0
        for raw in lines:
            try:
                snap = json.loads(raw)
            except json.JSONDecodeError:
                continue          # torn tail line: same rule as trend_days
            if isinstance(snap, dict):
                last = snap
                snapshots += 1
        if last is None or snapshots <= 1:
            continue              # nothing to collapse
        before = len(lines)
        kept = dict(last)
        kept["snapshots"] = snapshots
        report["files"].append({"file": path.name, "before": before,
                                "after": 1})
        report["before"] += before
        report["after"] += 1
        if not dry_run:
            path.write_text(json.dumps(kept, sort_keys=True) + "\n",
                            encoding="utf-8")
    report["before"] = report["before"] or sum(
        f["before"] for f in report["files"])
    return report


def rotate_digests(digest_dir: Path, keep_days: int) -> List[Path]:
    """Delete digest files older than ``keep_days``; returns removed."""
    cutoff = time.time() - keep_days * 86400
    removed = []
    for path in digest_dir.glob("digest-*.jsonl"):
        if path.stat().st_mtime < cutoff:
            path.unlink()
            removed.append(path)
    return removed


def _file_day(path: Path) -> Optional[str]:
    """YYYY-MM-DD from a digest file name, e.g. digest-20260918.jsonl."""
    stamp = path.stem.replace("digest-", "")
    if len(stamp) == 8 and stamp.isdigit():
        return f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:8]}"
    return None


def _snapshot_day(snap: dict, fallback: Optional[str]) -> str:
    """Day label for a snapshot; corrupt timestamps fall back to the
    file-name stamp, then to the epoch — digest files are untrusted
    input (tamper evidence lives in the ledger, not here)."""
    try:
        return datetime.datetime.fromtimestamp(
            float(snap.get("ts", time.time()))).strftime("%Y-%m-%d")
    except (TypeError, ValueError, OSError, OverflowError):
        return fallback or "1970-01-01"


def trend_days(digest_dir: Path) -> List[dict]:
    """One row per digest day: snapshot count plus the day's last
    snapshot as the day's fleet state."""
    seen: dict = {}
    order: List[str] = []
    for path in sorted(digest_dir.glob("digest-*.jsonl")):
        file_day = _file_day(path)
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line:
                continue
            try:
                snap = json.loads(line)
            except json.JSONDecodeError:
                continue  # torn tail line from an interrupted write
            if not isinstance(snap, dict):
                continue  # valid JSON, wrong shape: untrusted input
            day = _snapshot_day(snap, file_day)
            if day in seen:
                seen[day]["snapshots"] += 1
                seen[day]["last"] = snap
            else:
                order.append(day)
                seen[day] = {"day": day, "snapshots": 1, "last": snap}
    return [seen[day] for day in order]


def _trend_row(entry: dict) -> dict:
    """Fleet state for one digest day (trace-weighted failure rate)."""
    snap = entry["last"]
    stores = snap.get("stores") or []
    traces = sum(s.get("traces", 0) for s in stores)
    weighted = sum(s.get("failure_rate", 0.0) * s.get("traces", 0)
                   for s in stores)
    modes: dict = {}
    for s in stores:
        for m in s.get("top_modes") or []:
            modes[m.get("mode", "?")] = (
                modes.get(m.get("mode", "?"), 0) + m.get("count", 0))
    anomalies = sum(s.get("fleet_anomalies", 0) for s in stores)
    token_flags = sum(s.get("token_anomalies", 0) for s in stores)
    spend = sum(s.get("est_spend") or 0 for s in stores)
    breaches = sum(s.get("budget_breaches", 0) for s in stores)
    failures = sum(s.get("failures", 0) for s in stores)
    return {
        "day": entry["day"],
        "budget_breaches": breaches,
        "snapshots": entry["snapshots"],
        "stores": len(stores),
        "traces": traces,
        "failures": failures,
        "failure_rate": round(weighted / traces, 4) if traces else 0.0,
        "worsening": snap.get("worsening") or [],
        "top_modes": sorted(modes.items(), key=lambda kv: -kv[1])[:3],
        "fleet_anomalies": anomalies,
        "token_anomalies": token_flags,
        "est_spend": round(spend, 2),
    }


def summarize_trend(days: List[dict]) -> dict:
    """Fleet-level per-day series for the trend report.

    Failure rate is the trace-weighted mean across stores; verdict is
    the same Theil-Sen judgement the survey uses, applied to the day
    rates.
    """
    rows = [_trend_row(entry) for entry in days]
    verdict, slope = trend_verdict([r["failure_rate"] for r in rows])
    anomaly_series = [r["fleet_anomalies"] for r in rows]
    anomaly_verdict = None
    if len(anomaly_series) >= 2 and any(anomaly_series):
        a_verdict, a_slope = trend_verdict(anomaly_series)
        anomaly_verdict = {"verdict": a_verdict,
                           "slope": round(a_slope, 4),
                           "latest": anomaly_series[-1]}
    token_series = [r["token_anomalies"] for r in rows]
    token_verdict = None
    if len(token_series) >= 2 and any(token_series):
        t_verdict, t_slope = trend_verdict(token_series)
        token_verdict = {"verdict": t_verdict,
                         "slope": round(t_slope, 4),
                         "latest": token_series[-1]}
    spend_series = [r["est_spend"] for r in rows]
    spend_verdict = None
    if len(spend_series) >= 2 and any(spend_series):
        s_verdict, s_slope = trend_verdict(spend_series)
        spend_verdict = {"verdict": s_verdict,
                         "slope": round(s_slope, 4),
                         "latest": spend_series[-1]}
    breach_series = [r.get("budget_breaches", 0) for r in rows]
    breach_verdict = None
    if len(breach_series) >= 2 and any(breach_series):
        b_verdict, b_slope = trend_verdict(breach_series)
        breach_verdict = {"verdict": b_verdict,
                          "slope": round(b_slope, 4),
                          "latest": breach_series[-1]}
    return {"days": rows, "verdict": verdict, "slope": round(slope, 4),
            "snapshots": sum(r["snapshots"] for r in rows),
            "anomaly_trend": anomaly_verdict,
            "token_trend": token_verdict,
            "spend_trend": spend_verdict,
            "breach_trend": breach_verdict}


AGENT_TREND_KEYS = ("steps", "tool_calls", "errors",
                    "traces", "failed_traces")


def agent_trend_days(digest_dir: Path, agent: str) -> List[dict]:
    """Per-day rollup for one named agent from digest snapshots.

    Digest snapshots carry each store's top-3 busiest named agents
    (see webhook_payload); a day contributes an agent's row only while
    the agent stays among them — a zero row means "not observed", not
    "perfect". Digest files are untrusted input: missing or malformed
    fields read as zero.
    """
    days = []
    for day_row in trend_days(digest_dir):
        totals = dict.fromkeys(AGENT_TREND_KEYS, 0)
        last = day_row["last"]
        if not isinstance(last, dict):
            continue
        for store in (last.get("stores") or []):
            if not isinstance(store, dict):
                continue
            for row in (store.get("top_agents") or []):
                if not isinstance(row, dict) or row.get("agent") != agent:
                    continue
                for key in AGENT_TREND_KEYS:
                    value = row.get(key)
                    if isinstance(value, (int, float)) and value >= 0:
                        totals[key] += int(value)
        days.append({"day": day_row["day"], **totals})
    return days


def summarize_agent_trend(days: List[dict]) -> dict:
    """Verdict + sparkline inputs for one agent's touched-fail rate."""
    rates = [d["failed_traces"] / d["traces"] for d in days if d["traces"]]
    verdict, slope = trend_verdict(rates) if len(rates) >= 3 \
        else ("stable", 0.0)
    return {"days": days, "verdict": verdict, "slope": round(slope, 4),
            "observed_days": len(rates)}


def render_trend(summary: dict) -> str:
    """Terminal trend table with a fleet failure-rate sparkline."""
    from .cluster import sparkline

    days = summary["days"]
    lines = [(f"fleet trend - {len(days)} day(s), "
              f"{summary['snapshots']} snapshot(s)")]
    if not days:
        lines.append("  (no digest snapshots found)")
        return "\n".join(lines)
    lines.append("  day          snaps stores traces fail%  worsening  "
                 "top modes")
    for row in days:
        modes = ", ".join(f"{m} x{c}" for m, c in row["top_modes"]) or "-"
        worsen = ",".join(row["worsening"]) or "-"
        lines.append(
            f"  {row['day']}   {row['snapshots']:>5} {row['stores']:>6} "
            f"{row['traces']:>6} {row['failure_rate'] * 100:>5.1f}  "
            f"{worsen:<9}  {modes}")
    rates = [r["failure_rate"] for r in days]
    lines.append(f"  failure-rate sparkline: {sparkline(rates)}")
    last = days[-1]["failure_rate"]
    prev = days[-2]["failure_rate"] if len(days) > 1 else None
    tail = (f" (last day {prev * 100:.1f}% -> {last * 100:.1f}%)"
            if prev is not None else "")
    lines.append(f"  verdict: {summary['verdict']} "
                 f"(slope {summary['slope']:+.4f}/day){tail}")
    anomaly_trend = summary.get("anomaly_trend")
    if anomaly_trend:
        lines.append(
            f"  slowness trend: {anomaly_trend['verdict']} "
            f"(slope {anomaly_trend['slope']:+.4f}/day, latest "
            f"{anomaly_trend['latest']} flagged step(s))")
    token_trend = summary.get("token_trend")
    if token_trend:
        lines.append(
            f"  token-burn trend: {token_trend['verdict']} "
            f"(slope {token_trend['slope']:+.4f}/day, latest "
            f"{token_trend['latest']} flagged step(s))")
    spend_trend = summary.get("spend_trend")
    if spend_trend:
        lines.append(
            f"  spend trend: {spend_trend['verdict']} "
            f"(slope {spend_trend['slope']:+.2f}/day, latest "
            f"${spend_trend['latest']:,.2f})")
    return "\n".join(lines)


def _alert_reasons(summaries: list, threshold: Optional[float],
                   alert_anomalies: Optional[int],
                   alert_tokens: Optional[int],
                   alert_spend: Optional[float],
                   alert_budget_breaches: Optional[int] = None
                   ) -> frozenset:
    """Per-store alert reasons — the dedup key for cooldown.

    A frozenset of ``name:reason`` strings; an unchanged set inside
    the cooldown window is the same alarm still ringing, not a new
    one."""
    reasons = set()
    for s in summaries:
        if s.worsening:
            reasons.add(f"{s.name}:worsening")
        if threshold is not None and s.failure_rate >= threshold:
            reasons.add(f"{s.name}:failure-rate")
        if alert_anomalies is not None and \
                getattr(s, "fleet_anomalies", 0) >= alert_anomalies:
            reasons.add(f"{s.name}:anomalies")
        if alert_tokens is not None and \
                getattr(s, "token_anomalies", 0) >= alert_tokens:
            reasons.add(f"{s.name}:tokens")
        if alert_spend is not None and \
                getattr(s, "est_spend", None) is not None and \
                s.est_spend > alert_spend:
            reasons.add(f"{s.name}:spend")
        if alert_budget_breaches is not None and \
                getattr(s, "budget_breaches", 0) >= alert_budget_breaches:
            reasons.add(f"{s.name}:budget-breaches")
    return frozenset(reasons)


def _should_alert(summaries: list, threshold: Optional[float],
                  alert_anomalies: Optional[int] = None,
                  alert_tokens: Optional[int] = None,
                  alert_spend: Optional[float] = None,
                  alert_budget_breaches: Optional[int] = None) -> bool:
    """Quiet-by-default alerting: post only on signal, not on schedule.

    No thresholds: every cycle posts (the schedule is the signal).
    With ``alert_worse_than``: only when a store's trend is worsening
    or its failure rate is at/above the threshold. With
    ``alert_anomalies``/``alert_tokens``/``alert_spend``: also when a
    store carries at least that many fleet latency / token-burn
    outliers, or its estimated spend crosses the budget (needs
    prices in play — unpriced stores never trip the spend gate).
    ``alert_budget_breaches``: when at least that many runs carry the
    live rails' stamped breach.  A healthy fleet must not page anyone.
    """
    if threshold is None and alert_anomalies is None \
            and alert_tokens is None and alert_spend is None \
            and alert_budget_breaches is None:
        return True
    return any(
        s.worsening
        or (threshold is not None and s.failure_rate >= threshold)
        or (alert_anomalies is not None
            and getattr(s, "fleet_anomalies", 0) >= alert_anomalies)
        or (alert_tokens is not None
            and getattr(s, "token_anomalies", 0) >= alert_tokens)
        or (alert_spend is not None
            and (getattr(s, "est_spend", None) or 0) >= alert_spend)
        or (alert_budget_breaches is not None
            and getattr(s, "budget_breaches", 0) >= alert_budget_breaches)
        for s in summaries)


def watch_fleet(stores: List[Path], digest_dir: Path, interval: float,
                keep_days: int = 30, iterations: Optional[int] = None,
                top_agents: int = 3,
                sleep: Any = time.sleep,
                webhook_url: Optional[str] = None,
                notify: Any = None,
                alert_worse_than: Optional[float] = None,
                alert_anomalies: Optional[int] = None,
                alert_tokens: Optional[int] = None,
                alert_spend: Optional[float] = None,
                alert_budget_breaches: Optional[int] = None,
                prices: Optional[dict] = None,
                alert_cooldown: float = 0.0,
                clock: Any = time.monotonic) -> int:
    """Poll the fleet forever (or ``iterations`` times), appending
    snapshots. Returns the number of snapshots written. ``sleep`` is
    injectable so tests run instantly.  Each start also compacts the
    digest history (one line per day) so a long-lived watch never
    needs a manual drain; the next append continues from the
    compacted form.

    With ``webhook_url`` every cycle also POSTs the fleet summary
    (same HMAC-signed payload as the one-shot notify). Delivery
    failure is a stderr warning, never a stopped watch: an ops loop
    must survive the notification endpoint being down.
    """
    written = 0
    rotate_digests(digest_dir, keep_days)
    compact_digests(digest_dir)
    last_reasons: Optional[frozenset] = None
    last_alert_at: Optional[float] = None
    last_day_file: Optional[Path] = None
    for _ in (range(iterations) if iterations is not None
              else iter(int, 1)):
        summaries = survey(stores, top_agents, prices=prices)
        day_file = append_digest(digest_dir,
                                 digest_snapshot(summaries))
        written += 1
        if last_day_file is not None and day_file != last_day_file:
            # midnight crossed: the finished day collapses to its
            # final line right here, without waiting for a restart
            compact_digests(digest_dir)
        last_day_file = day_file
        if webhook_url and _should_alert(summaries, alert_worse_than,
                                         alert_anomalies,
                                         alert_tokens, alert_spend,
                                         alert_budget_breaches):
            # cooldown: the SAME alarm ringing every cycle is an
            # alarm storm, not signal.  Re-pages happen when the
            # reason set GROWS (a new store degraded, a new gate
            # tripped) or after the cooldown lapses.
            reasons = _alert_reasons(summaries, alert_worse_than,
                                     alert_anomalies, alert_tokens,
                                     alert_spend,
                                     alert_budget_breaches)
            now = clock()
            grown = bool(reasons - (last_reasons or frozenset()))
            lapsed = (last_alert_at is None
                      or now - last_alert_at >= alert_cooldown)
            # fresh = first page, a GROWN reason set (a new store
            # degraded, a new gate tripped), or a lapsed cooldown.
            # Note a threshold-less watch carries an empty reason
            # set — same empty set is the same alarm, not a new one.
            fresh = last_reasons is None or grown or lapsed
            if fresh:
                poster = notify or notify_webhook
                try:
                    poster(summaries, webhook_url)
                    last_reasons = reasons
                    last_alert_at = now
                except Exception as exc:
                    print(f"watch: webhook delivery failed: {exc}",
                          file=sys.stderr)
        sleep(interval)
    return written
