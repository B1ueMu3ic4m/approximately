"""The digest: one shift-start brief, composed from the ops doors.

``audit`` gives the 3am cron one exit code; ``digest`` gives the
on-call human one page at shift start: this week vs last, the grades
on the wall, the top of the triage queue, and today's failed
arrivals. It composes doors, it is not a new analysis — week_compare
owns the weeks, grade owns the letters, triage owns the queue, the
tail owns arrivals. Every section can be absent and says so in
prose; an absent section is a finding, never a blank.
"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path
from typing import Any, Dict, List, Optional


def _week_section(store: Any, digest_dir: Optional[str],
                  ref: _dt.date) -> Optional[dict]:
    """The week-over-week numbers, or None without a digest dir."""
    if not digest_dir or not Path(digest_dir).is_dir():
        return None
    from .fleet import summarize_trend, trend_days, week_compare

    rows = summarize_trend(trend_days(Path(digest_dir)))["days"]
    return week_compare(rows, today=ref)


def _grade_section(store: Any, grade_floor: Optional[str],
                   payload: Dict[str, Any]) -> None:
    """Fill the grades in place; an unknown floor raises (refusal)."""
    from .grade import below_floor, grade_store

    try:
        grades, kind = grade_store(store)
    except KeyError:
        grades, kind = [], "agent"
    payload["grades"] = grades
    payload["grade_kind"] = kind
    if grade_floor is not None and grades:
        payload["below_floor"] = [
            {"subject": r["subject"], "grade": r["grade"]}
            for r in below_floor(grades, grade_floor)]


def _arrival_section(store: Any, ref: _dt.date) -> dict:
    """Today's arrivals: counts plus the failed runs' payloads."""
    from .tail import arrival_payload, scan_pass
    from .trace import coerce_epoch

    day_start = _dt.datetime.combine(
        ref, _dt.time.min).timestamp()
    arrivals: Dict[str, Any] = {"failed": 0, "ok": 0, "lines": []}
    for trace in scan_pass(store, set()):
        if coerce_epoch(trace.created_at) < day_start:
            continue
        if trace.success is False:
            arrivals["failed"] += 1
            arrivals["lines"].append(arrival_payload(trace))
        else:
            arrivals["ok"] += 1
    return arrivals


def build_digest(store: Any,
                 digest_dir: Optional[str] = None,
                 triage_top: int = 5,
                 grade_floor: Optional[str] = None,
                 today: Optional[_dt.date] = None) -> dict:
    """The structured shift brief. Raises ValueError on an unknown
    grade floor (the refusal the audit door uses), never on data:
    an empty store yields a brief whose sections say they are
    empty."""
    from .triage import triage_store

    ref = today or _dt.date.today()
    payload: Dict[str, Any] = {
        "store": str(store.directory),
        "generated": _dt.datetime.now().isoformat(timespec="seconds"),
        "week": _week_section(store, digest_dir, ref),
        "grades": [],
        "grade_kind": "agent",
        "below_floor": [],
        "triage": [r.to_dict() for r in
                   triage_store(store)[:max(0, int(triage_top))]],
        "arrivals": _arrival_section(store, ref),
    }
    _grade_section(store, grade_floor, payload)
    return payload


def _delta_pct(d: Optional[float]) -> str:
    if d is None:
        return "n/a"
    return f"{d:+.0%}"


def _render_week(week: Optional[dict]) -> List[str]:
    if not week or not week.get("usable"):
        return ["not usable yet — one of the weeks has no rows"]
    d = week["deltas"]
    return [
        (f"- traces {week['this_week']['traces']} "
         f"({_delta_pct(d['traces'])} vs last week)"),
        (f"- failures {week['this_week']['failures']} "
         f"({_delta_pct(d['failures'])})"),
        (f"- est spend ${week['this_week']['est_spend']} "
         f"({_delta_pct(d['est_spend'])})"),
    ]


def _render_grades(payload: dict) -> List[str]:
    grades = payload["grades"]
    if not grades:
        return [("no grades — fewer than the two traces a "
                 "scorecard needs")]
    lines = []
    for g in grades:
        flag = " BELOW FLOOR" if any(
            b["subject"] == g["subject"]
            for b in payload["below_floor"]) else ""
        lines.append(f"- {g['subject']}: {g['grade']}{flag}")
    return lines


def _render_triage(payload: dict) -> List[str]:
    if not payload["triage"]:
        return ["nothing to triage — no failed traces in the "
                "window"]
    lines = []
    for r in payload["triage"]:
        task = " ".join(str(r.get("task") or "").split())[:48]
        lines.append(f"- {r['mode']} {r['trace_id']} "
                     f"score {r['score']} — {task}")
    return lines


def _render_arrivals(payload: dict) -> List[str]:
    arr = payload["arrivals"]
    lines = [f"{arr['failed']} failed / {arr['ok']} ok"]
    for a in arr["lines"]:
        t = a["trace"]
        task = " ".join(str(t.get("task") or "").split())[:48]
        lines.append(f"- FAIL {t['id']} {t['steps']} steps — {task}")
    return lines


def render_markdown(payload: dict) -> str:
    """The human page. Sections render even when empty — the brief
    always names what it does not know."""
    lines = [f"# ops digest — {payload['store']}",
             f"generated {payload['generated']}", "",
             "## this week vs last"]
    lines += _render_week(payload["week"])
    lines += ["", "## grades"] + _render_grades(payload)
    lines += ["", "## triage queue"] + _render_triage(payload)
    lines += ["", "## today's arrivals"] + _render_arrivals(payload)
    return "\n".join(lines) + "\n"
