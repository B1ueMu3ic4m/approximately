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
from typing import List, Optional

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

    @property
    def worsening(self) -> bool:
        return self.trend_verdict == "worsening"


def _verdict(trend_rows: List[dict]) -> tuple:
    """Theil-Sen verdict over the store's failure-rate history."""
    rates = [r["failed"] / r["total"] for r in trend_rows if r.get("total")]
    return trend_verdict(rates)


def _top_agents(traces, n: int = 3) -> List[dict]:
    """Busiest named agents across the store (scorecard order)."""
    return [r for r in agent_scorecard(traces)
            if r["agent"] != UNATTRIBUTED][:n]


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
                "top_agents": [
                    {k: r[k] for k in ("agent", "steps", "tool_calls",
                                       "errors", "tokens", "failed_traces",
                                       "failure_rate")}
                    for r in s.top_agents
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
    import hmac
    import json as _json

    scheme = urllib.parse.urlparse(url).scheme.lower()
    if scheme not in ("http", "https"):
        # also blocks file:// and custom schemes from sneaking in
        # through configuration
        raise RuntimeError(f"webhook URL must be http(s), got {scheme!r}")

    body = _json.dumps(webhook_payload(summaries),
                       sort_keys=True).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if signing_key:
        digest = hmac.new(signing_key, body, hashlib.sha256).hexdigest()
        headers["X-Approximately-Signature"] = f"sha256={digest}"
    request = urllib.request.Request(url, data=body, headers=headers,
                                     method="POST")
    attempts = 2  # one retry for transient transport failures
    last_error: Exception = RuntimeError("no attempt made")
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(  # nosec B310: scheme checked above
                    request, timeout=timeout) as response:
                return f"{response.status}"
        except urllib.error.HTTPError as exc:
            # a definite answer from the endpoint: retrying a 4xx/5xx
            # would just re-announce the same summary
            return f"HTTP {exc.code}"
        except (urllib.error.URLError, OSError) as exc:
            last_error = exc
            if attempt < attempts:
                time.sleep(0.5 * attempt)  # brief backoff, bounded
    raise RuntimeError(
        f"webhook delivery failed after {attempts} attempts: "
        f"{last_error}") from last_error


def survey(stores: List[Path], top_agents: int = 3) -> List[StoreSummary]:
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
        rows = trend(traces)
        verdict, slope = _verdict(rows)
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
    agents_html = "".join(
        "<tr><td class='mono'>" + esc(r["agent"]) + "</td>"
        f"<td>{r['steps']}</td><td>{r['errors']}</td>"
        f"<td>{r['failure_rate']:.0%}</td></tr>"
        for r in s.top_agents
    ) or "<tr><td>no named agents recorded</td></tr>"
    return (
        f'<div class="store"><h2>{esc(s.name)}</h2>'
        f'<div class="sub">{esc(s.path)} · '
        f'{s.traces} traces · ledger: {ledger_note}</div>'
        '<div class="row">'
        f'<span class="rate {rate_cls}">{s.failure_rate:.0%}</span>'
        f"{spark}"
        f'<span class="badge {badge_cls}">{esc(trend_label)}</span>'
        "</div>"
        "<h3>Top failure modes</h3>"
        f"<table>{modes_html}</table>"
        "<h3>Busiest agents</h3>"
        "<table>"
        "<tr><th>agent</th><th>steps</th><th>errors</th>"
        "<th>fail-rate</th></tr>"
        + agents_html + "</table></div>"
    )


def _trend_section(summary: dict) -> str:
    """HTML block for the digest-history trend (render_fleet_html)."""
    import html as _html

    esc = _html.escape
    rates = [r["failed"] / r["total"] * 100 for r in summary["days"]
             if r.get("total")]
    spark = render_sparkline(rates, width=420, height=70) if rates \
        else "<p>(no snapshots with traces yet)</p>"
    badge_cls, trend_label = TREND_LABELS[summary["verdict"]]
    rows = "".join(
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
        "<th>failure rate</th></tr>" + rows + "</table></div>")


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
    return {
        "day": entry["day"],
        "snapshots": entry["snapshots"],
        "stores": len(stores),
        "traces": traces,
        "failure_rate": round(weighted / traces, 4) if traces else 0.0,
        "worsening": snap.get("worsening") or [],
        "top_modes": sorted(modes.items(), key=lambda kv: -kv[1])[:3],
    }


def summarize_trend(days: List[dict]) -> dict:
    """Fleet-level per-day series for the trend report.

    Failure rate is the trace-weighted mean across stores; verdict is
    the same Theil-Sen judgement the survey uses, applied to the day
    rates.
    """
    rows = [_trend_row(entry) for entry in days]
    verdict, slope = trend_verdict([r["failure_rate"] for r in rows])
    return {"days": rows, "verdict": verdict, "slope": round(slope, 4),
            "snapshots": sum(r["snapshots"] for r in rows)}


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
    return "\n".join(lines)


def watch_fleet(stores: List[Path], digest_dir: Path, interval: float,
                keep_days: int = 30, iterations: Optional[int] = None,
                top_agents: int = 3, sleep=time.sleep,
                webhook_url: Optional[str] = None,
                notify: Optional[callable] = None) -> int:
    """Poll the fleet forever (or ``iterations`` times), appending
    snapshots. Returns the number of snapshots written. ``sleep`` is
    injectable so tests run instantly.

    With ``webhook_url`` every cycle also POSTs the fleet summary
    (same HMAC-signed payload as the one-shot notify). Delivery
    failure is a stderr warning, never a stopped watch: an ops loop
    must survive the notification endpoint being down.
    """
    written = 0
    rotate_digests(digest_dir, keep_days)
    for _ in (range(iterations) if iterations is not None
              else iter(int, 1)):
        summaries = survey(stores, top_agents)
        append_digest(digest_dir, digest_snapshot(summaries))
        written += 1
        if webhook_url:
            poster = notify or notify_webhook
            try:
                poster(summaries, webhook_url)
            except Exception as exc:
                print(f"watch: webhook delivery failed: {exc}",
                      file=sys.stderr)
        sleep(interval)
    return written
