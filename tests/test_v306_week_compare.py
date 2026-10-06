"""v306: the week-over-week audit line — v3.4.0.

The nightly audit already projects (spend forecast, reliability
budget); `--week-compare` adds the retrospective half: this ISO
week vs last over the digest's day-rows — failures, spend, volume,
deltas honest about division by zero. A comparison of nothing is
not a comparison (usable=False), and the MCP audit carries the
same section.
"""

import argparse
import contextlib
import datetime
import io
import json

from approximately.cli import cmd_audit
from approximately.fleet import summarize_trend, week_compare
from approximately.mcp_server import ServerContext, _tool_audit
from approximately.recorder import Recorder
from approximately.store import TraceStore

_TODAY = datetime.date.today()


def _day(offset_days: int) -> str:
    return str(_TODAY - datetime.timedelta(days=offset_days))


def _digest_rows(tmp_path, failures_by_day):
    """A real digest dir: one snapshot line per day, in the
    on-disk shapes the fleet door actually reads (compact
    digest-YYYYMMDD.jsonl names, epoch ts)."""
    dd = tmp_path / "d"
    dd.mkdir(exist_ok=True)
    for day, failures in failures_by_day.items():
        noon = datetime.datetime.fromisoformat(day + "T12:00:00")
        frame = {"ts": noon.timestamp(), "stores": [{
            "store": str(tmp_path / "s"), "traces": 10,
            "failures": failures, "est_spend": 1.0,
            "successes": 10 - failures, "steps": 30,
            "tokens": 900, "top_modes": {}, "p95_ms": 100.0,
        }]}
        stamp = day.replace("-", "")
        (dd / f"digest-{stamp}.jsonl").write_text(
            json.dumps(frame) + "\n", encoding="utf-8")
    return dd


def _audit_args(tmp_path, **kw):
    base = {"store": str(tmp_path), "digest_dir": str(tmp_path / "d"),
            "spend_ceiling": None, "failure_budget": None,
            "deep": False, "fix": False, "fail_on_worsening": False,
            "prices": None, "since": None,
            "max_failure_rate": None, "max_tokens": None,
            "max_budget_breaches": None, "max_result_chars": None,
            "max_latency_ms": None, "max_repeated_actions": None,
            "max_steps": None, "grade_floor": None,
            "triage_top": None, "week_compare": True, "json": True}
    base.update(kw)
    return argparse.Namespace(**base)


def test_week_compare_shapes():
    rows = summarize_trend([
        {"day": _day(o), "snapshots": 1,
         "last": {"failures": o % 3, "est_spend": 1.0,
                  "stores": [{"traces": 10, "failures": o % 3,
                              "est_spend": 1.0}]}}
        for o in range(1, 15)])
    r = week_compare(rows["days"])
    assert r["usable"] is True
    assert set(r["deltas"]) == {"failures", "traces", "est_spend"}
    assert r["this_week"]["days"] >= 1
    assert r["last_week"]["days"] >= 1


def test_week_compare_unusable_on_empty():
    r = week_compare([])
    assert r["usable"] is False
    assert r["deltas"]["failures"] is None


def test_audit_report_carries_the_week(tmp_path):
    store = TraceStore(tmp_path)
    with Recorder("ok run", store=store) as rec:
        rec.tool("sh", {}, result="fine")
    # this week: 2+3+1 (Mon..); last week: 5+6+4 — anchored to the
    # ISO Monday so the test is weekday-independent
    monday = _TODAY - datetime.timedelta(days=_TODAY.weekday())

    def d(offset_from_monday: int) -> str:
        return str(monday + datetime.timedelta(
            days=offset_from_monday))

    _digest_rows(tmp_path, {d(o): f for o, f in
                            ((0, 2), (1, 3), (2, 1),
                             (-7, 5), (-6, 6), (-5, 4))})
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        assert cmd_audit(_audit_args(tmp_path)) == 0
    payload = json.loads(buf.getvalue())
    assert payload["week"]["usable"] is True
    assert payload["week"]["this_week"]["failures"] == 6
    assert payload["week"]["last_week"]["failures"] == 15


def test_prose_line_renders(tmp_path, capsys):
    TraceStore(tmp_path)
    with Recorder("ok run", store=TraceStore(tmp_path)) as rec:
        rec.tool("sh", {}, result="fine")
    monday = _TODAY - datetime.timedelta(days=_TODAY.weekday())

    def d(offset_from_monday: int) -> str:
        return str(monday + datetime.timedelta(
            days=offset_from_monday))

    _digest_rows(tmp_path, {d(o): f for o, f in ((0, 2), (-7, 5))})
    args = _audit_args(tmp_path, json=False)
    assert cmd_audit(args) == 0
    out = capsys.readouterr().out
    assert "week:" in out and "WoW" in out


def test_mcp_audit_week(tmp_path):
    store = TraceStore(tmp_path)
    with Recorder("ok", store=store) as rec:
        rec.tool("sh", {}, result="fine")
    monday = _TODAY - datetime.timedelta(days=_TODAY.weekday())

    def d(offset_from_monday: int) -> str:
        return str(monday + datetime.timedelta(
            days=offset_from_monday))

    _digest_rows(tmp_path, {d(o): f for o, f in ((0, 2), (-7, 5))})
    rep = _tool_audit(ServerContext(str(tmp_path)),
                      {"digest_dir": str(tmp_path / "d"),
                       "week_compare": True})
    assert rep["week"]["usable"] is True
    assert rep["week"]["this_week"]["failures"] == 2
    assert rep["week"]["last_week"]["failures"] == 5
