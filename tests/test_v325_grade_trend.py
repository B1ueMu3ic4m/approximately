"""v325: grade --trend — week-over-week letter drift.

"Which agent is drifting?" is a status line; the trend door
quantifies it: this week's grade vs last week's, from the trace's
own clock. Thin evidence (n/a on either side) is reported as thin,
never as a verdict; a subject only on file last week reads gone,
only this week, new.
"""

import argparse
import json
import tempfile
import time

from approximately.cli import cmd_grade
from approximately.grade import grade_trend, render_grade_trend
from approximately.mcp_server import ServerContext, _tool_grade
from approximately.store import TraceStore
from approximately.trace import Step, Trace

NOW = time.time()


def _trace(store, task, agent, success, age_days):
    t = Trace(task=task, model="m")
    t.add(Step(kind="tool_call", tool="sh", result="x", tokens=5,
               agent=agent))
    t.success = success
    t.created_at = NOW - age_days * 86400.0
    store.save(t)
    return t


def _store():
    store = TraceStore(tempfile.mkdtemp())
    # this week: ace is clean, ghost only worked last week
    for i in range(4):
        _trace(store, f"ace ok {i}", "ace", True, i + 0.5)
    _trace(store, "ace botch", "ace", False, 1.2)
    # last week: ace was perfect, drifter was perfect, ghost left
    for i in range(6):
        _trace(store, f"ace old ok {i}", "ace", True, 9 + i * 0.4)
    for i in range(6):
        _trace(store, f"drifter old ok {i}", "drifter", True,
               9 + i * 0.4)
    for i in range(4):
        _trace(store, f"ghost old ok {i}", "ghost", True,
               9 + i * 0.4)
    # this week the drifter slips
    for i in range(6):
        _trace(store, f"drifter fail {i}", "drifter", False, i + 0.4)
    # steady: identical weeks, so the letters must agree
    for i in range(6):
        _trace(store, f"steady old ok {i}", "steady", True,
               9 + i * 0.4)
    _trace(store, "steady old botch", "steady", False, 9.5)
    for i in range(6):
        _trace(store, f"steady ok {i}", "steady", True, i + 0.4)
    _trace(store, "steady botch", "steady", False, 0.5)
    return store


def test_trend_names_the_drift():
    trend = grade_trend(_store(), now=NOW)
    rows = {r["subject"]: r for r in trend["subjects"]}
    assert rows["drifter"]["direction"] == "slipped"
    assert rows["steady"]["direction"] == "flat"
    assert rows["ace"]["direction"] in ("flat", "slipped")
    assert rows["ghost"] == {"subject": "ghost", "now": None,
                             "prev": rows["ghost"]["prev"],
                             "direction": "gone"}
    assert trend["this_week_traces"] == 18
    assert trend["last_week_traces"] == 23


def test_thin_evidence_never_gets_a_direction():
    store = TraceStore(tempfile.mkdtemp())
    _trace(store, "single run this week", "solo", False, 1)
    trend = grade_trend(store, now=NOW)
    row = trend["subjects"][0]
    assert row["direction"] == "new"  # one-sided: no verdict claimed
    assert row["prev"] is None


def test_render_names_flat_and_unusable():
    trend = grade_trend(_store(), now=NOW)
    page = render_grade_trend(trend)
    assert "grade trend (agents" in page
    assert "(slipped)" in page and "(flat)" in page
    empty = grade_trend(TraceStore(tempfile.mkdtemp()), now=NOW)
    assert "no two-week evidence" in render_grade_trend(empty)


def test_cli_and_mcp_carry_trend(tmp_path, capsys):
    store = _store()
    args = argparse.Namespace(store=store.directory, agent=None,
                              tool=None, trend=True, json=False)
    assert cmd_grade(args) == 0
    assert "grade trend" in capsys.readouterr().out
    args.json = True
    assert cmd_grade(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["kind"] == "agent"
    assert {r["subject"] for r in payload["subjects"]} >= {"ace"}
    mcp = _tool_grade(ServerContext(store.directory),
                      {"trend": True})
    assert mcp["usable"] is True
    assert mcp["subjects"]
