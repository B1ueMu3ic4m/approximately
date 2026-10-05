"""v301: the audit door carries the night's verdicts.

``audit --grade-floor B`` fails the nightly door when any agent
grades below the floor (``n/a`` never fails — insufficient evidence
is not a conviction); ``--triage-top N`` attaches the morning queue
to the report as advice, never an exit verdict. The 3am cron now
speaks the whole on-call loop.
"""

import argparse
import contextlib
import io
import json

import pytest

from approximately.cli import cmd_audit
from approximately.grade import below_floor
from approximately.mcp_server import ServerContext, _tool_audit
from approximately.store import TraceStore
from approximately.trace import Step, Trace


def _seed(tmp_path, good_runs=10, bad_runs=5, bad_ok=2):
    store = TraceStore(tmp_path)
    for i in range(good_runs):
        t = Trace(task=f"g{i}", model="m")
        t.add(Step(kind="tool_call", tool="sh", agent="good",
                   result="ok"))
        t.success = True
        store.save(t)
    for i in range(bad_runs):
        t = Trace(task=f"b{i}", model="m")
        t.add(Step(kind="tool_call", tool="sh", agent="bad",
                   result="x", error="boom"))
        t.success = i >= bad_ok
        if i < bad_ok:
            t.success = False
        store.save(t)
    return store


def _audit_args(tmp_path, **extra):
    base = {"store": str(tmp_path), "digest_dir": None,
            "spend_ceiling": None, "failure_budget": None,
            "deep": False, "fix": False, "fail_on_worsening": False,
            "prices": None, "since": None,
            "max_failure_rate": None, "max_tokens": None,
            "max_budget_breaches": None,
            "max_result_chars": None, "max_latency_ms": None,
            "max_repeated_actions": None, "max_steps": None,
            "json": True}
    base.update(extra)
    return argparse.Namespace(**base)


def test_grade_floor_fails_the_audit(tmp_path):
    _seed(tmp_path)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = cmd_audit(_audit_args(tmp_path, **{
            "grade_floor": "A", "triage_top": 2}))
    assert code == 1
    payload = json.loads(buf.getvalue())
    assert payload["ok"] is False
    below = {b["subject"] for b in payload["grades"]["below"]}
    assert "bad" in below and "good" not in below
    assert len(payload["triage"]) == 2


def test_grade_floor_passes_when_earned(tmp_path):
    _seed(tmp_path, good_runs=10, bad_runs=5, bad_ok=5)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = cmd_audit(_audit_args(tmp_path,
                                     **{"grade_floor": "F"}))
    assert code == 0
    payload = json.loads(buf.getvalue())
    assert payload["grades"]["below"] == []


def test_triage_top_is_advice_only(tmp_path):
    _seed(tmp_path)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = cmd_audit(_audit_args(tmp_path,
                                     **{"triage_top": 3}))
    assert code == 0  # the queue never flips the verdict
    payload = json.loads(buf.getvalue())
    assert len(payload["triage"]) == 2  # the seed has 2 failures
    row = payload["triage"][0]
    assert {"novelty", "cost", "blast", "recency"} == \
        set(row["parts"])


def test_unknown_floor_refuses(tmp_path, capsys):
    _seed(tmp_path)
    code = cmd_audit(_audit_args(tmp_path, **{"grade_floor": "E"}))
    assert code == 2
    assert "grade floor" in capsys.readouterr().err


def test_below_floor_semantics():
    rows = [{"subject": "a", "grade": "A"},
            {"subject": "b", "grade": "C"},
            {"subject": "c", "grade": "n/a"}]
    assert [r["subject"] for r in below_floor(rows, "B")] == ["b"]
    assert below_floor(rows, "A") == [{"subject": "b",
                                       "grade": "C"}]
    assert below_floor(rows, "F") == []  # nothing below failure
    with pytest.raises(ValueError, match="grade floor"):
        below_floor(rows, "E")


def test_mcp_audit_floor_and_triage(tmp_path):
    _seed(tmp_path)
    rep = _tool_audit(ServerContext(str(tmp_path)),
                      {"grade_floor": "A", "triage_top": 2})
    assert rep["ok"] is False
    assert rep["grades"]["below"][0]["subject"] == "bad"
    assert len(rep["triage"]) == 2
    assert _tool_audit(ServerContext(str(tmp_path)),
                       {"grade_floor": "F"})["ok"] is True
    with pytest.raises(KeyError, match="grade floor"):
        _tool_audit(ServerContext(str(tmp_path)),
                    {"grade_floor": "Z"})
