"""v329: the glance and the ledger — status reads the drift, the
audit speaks JUnit.

``status`` is the one-glance overview; week-over-week grade drift
was the one thing it made you run another door for. Now the drift
line rides the frame (and the JSON payload). ``audit --format
junit`` renders each finding — doctor, every gate row, grade floor,
prices, trend, spend ceiling, failure budget — as a failing
testcase, the same native rendering the ci door gives its gates.
"""

import argparse
import json
import tempfile

from approximately.cli import cmd_audit, cmd_status
from approximately.recorder import Recorder
from approximately.store import TraceStore
from approximately.trace import Step, Trace


def _seed(store, agent, ok_count, fail_count, age_days):
    import time as _t

    for i in range(ok_count):
        t = Trace(task=f"{agent} ok {i}", model="m")
        t.add(Step(kind="tool_call", tool="sh", result="x", tokens=5,
                   agent=agent))
        t.success = True
        t.created_at = _t.time() - (age_days + i * 0.1) * 86400.0
        store.save(t)
    for i in range(fail_count):
        t = Trace(task=f"{agent} fail {i}", model="m")
        t.add(Step(kind="tool_call", tool="sh", result="x", tokens=5,
                   agent=agent))
        t.success = False
        t.created_at = _t.time() - (age_days + i * 0.1) * 86400.0
        store.save(t)


def _status_out(store, json_mode=False):
    import contextlib
    import io

    args = argparse.Namespace(store=store.directory, watch=False,
                              json=json_mode, since=None,
                              digest_dir=None, spend_ceiling=None,
                              failure_budget=None, on_change=False,
                              interval=30.0, prices=None)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        assert cmd_status(args) == 0
    return buf.getvalue()


def test_status_names_the_drift():
    store = TraceStore(tempfile.mkdtemp())
    _seed(store, "ace", ok_count=6, fail_count=0, age_days=9)
    _seed(store, "ace", ok_count=4, fail_count=2, age_days=1)
    prose = _status_out(store)
    assert "grade drift" in prose and "slipped: ace" in prose
    payload = json.loads(_status_out(store, json_mode=True))
    drift = payload["grade_trend"]
    assert drift["usable"] is True
    assert drift["slipped"] == ["ace"]
    assert drift["improved"] == []


def test_status_stays_quiet_without_drift():
    store = TraceStore(tempfile.mkdtemp())
    _seed(store, "steady", ok_count=5, fail_count=1, age_days=9)
    _seed(store, "steady", ok_count=5, fail_count=1, age_days=1)
    prose = _status_out(store)
    assert "grade drift" not in prose, \
        "flat weeks are not news"
    payload = json.loads(_status_out(store, json_mode=True))
    assert payload["grade_trend"]["slipped"] == []
    assert payload["grade_trend"]["improved"] == []


def _audit_args(store, **kw):
    base = {"store": store.directory, "since": None, "deep": False,
            "fix": False, "digest_dir": None, "spend_ceiling": None,
            "failure_budget": None, "fail_on_worsening": False,
            "grade_floor": None, "triage_top": None, "json": False,
            "format": None, "week_compare": False,
            "max_failure_rate": 1.1}
    base.update(kw)
    return argparse.Namespace(**base)


def test_audit_junit_maps_findings_to_testcases():
    store = TraceStore(tempfile.mkdtemp())
    with Recorder("boom", store=store) as rec:
        rec.tool("sh", {}, agent="bot", result="x")
        rec.fail("boom")
    with Recorder("fine", store=store) as rec:
        rec.tool("sh", {}, agent="bot", result="ok")
        rec.respond("done", success=True)
    # every gate passes; the failing-run rate is 50%: cap at 1.0
    args = _audit_args(store, format="junit",
                       max_failure_rate=0.1)
    import contextlib
    import io

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = cmd_audit(args)
    assert rc == 1  # the failure-rate gate must breach
    xml = buf.getvalue()
    assert "approximately-audit" in xml
    assert "<failure" in xml
    assert 'name="failure-rate"' in xml
    assert 'name="doctor"' in xml


def test_audit_junit_clean_audit_has_no_failures():
    store = TraceStore(tempfile.mkdtemp())
    with Recorder("fine", store=store) as rec:
        rec.tool("sh", {}, agent="bot", result="ok")
        rec.respond("done", success=True)
    args = _audit_args(store, format="junit",
                       max_failure_rate=1.1)
    import contextlib
    import io

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        assert cmd_audit(args) == 0
    xml = buf.getvalue()
    assert "<failure" not in xml
    assert 'name="doctor"' in xml
