"""v296: letter grades — scorecards become verdicts.

``grade`` turns the cluster scorecards' per-subject rollups into
letters: reliability (0.5), discipline (0.25), budget (0.25 — any
breach stamp is an F). Evidence floors: under 2 traces grades n/a,
never a guess; weights renormalize when a component lacks evidence.
"""

import argparse
import contextlib
import io
import json

import pytest

from approximately.cli import cmd_grade
from approximately.grade import (grade_card, grade_cards,
                                 grade_store, render_grades)
from approximately.mcp_server import ServerContext, _tool_grade
from approximately.store import TraceStore
from approximately.trace import Step, Trace


def _seed(store, agent, runs, fail_idx=(), breach_idx=(),
          error_every=False):
    for i in range(runs):
        t = Trace(task=f"{agent} run {i}", model="m")
        t.add(Step(kind="tool_call", tool="sh", agent=agent,
                   result="ok" if not error_every or i in fail_idx
                   else "x",
                   error="boom" if (error_every and i in fail_idx)
                   else None,
                   latency_ms=100))
        t.success = i not in fail_idx
        if i in breach_idx:
            t.meta["budget"] = {"exceeded": True}
        store.save(t)


def test_clean_agent_grades_a():
    import tempfile

    store = TraceStore(tempfile.mkdtemp())
    _seed(store, "good-bot", 10, fail_idx=(9,))
    rows, kind = grade_store(store)
    row = rows[0]
    assert kind == "agent" and row["subject"] == "good-bot"
    # 1/10 failure -> B reliability, A discipline, A budget;
    # weighted 3*0.5 + 4*0.25 + 4*0.25 = 3.5 -> A
    assert (row["reliability"], row["discipline"],
            row["budget"]) == ("B", "A", "A")
    assert row["grade"] == "A"


def test_recidivist_grades_f():
    import tempfile

    store = TraceStore(tempfile.mkdtemp())
    _seed(store, "bad-bot", 5, fail_idx=(0, 1, 2, 3),
          breach_idx=(0, 1), error_every=True)
    rows, _ = grade_store(store)
    row = rows[0]
    assert row["grade"] == "F"
    assert row["budget"] == "F"  # a breach is binary evidence
    assert row["reliability"] == "F"


def test_insufficient_evidence_is_na():
    import tempfile

    store = TraceStore(tempfile.mkdtemp())
    _seed(store, "one-off", 1, fail_idx=(0,))
    rows, _ = grade_store(store)
    assert rows[0]["grade"] == "n/a"
    assert rows[0]["reliability"] is None
    assert "n/a" in render_grades(rows)


def test_weights_renormalize_without_tool_calls():
    # B reliability, no calls, A budget -> 3*0.5 + 4*0.25 over 0.75
    # = 3.333 -> B, discipline None
    row = grade_card({"agent": "x", "traces": 5,
                      "failure_rate": 0.1, "errors": 0,
                      "tool_calls": 0, "breached_traces": 0})
    assert (row["grade"], row["discipline"]) == ("B", None)
    # all-message agents: no call evidence never becomes an F


def test_ranking_best_first_and_na_last():
    import tempfile

    store = TraceStore(tempfile.mkdtemp())
    _seed(store, "mid-bot", 10, fail_idx=(0, 1, 2))  # 0.3 -> C rel
    _seed(store, "best-bot", 10, fail_idx=())
    _seed(store, "one-off", 1)
    rows, _ = grade_store(store)
    subjects = [r["subject"] for r in rows]
    assert subjects[0] == "best-bot"
    assert subjects[-1] == "one-off"  # n/a sinks to the bottom


def test_tools_grade_and_subject_narrowing():
    import tempfile

    store = TraceStore(tempfile.mkdtemp())
    for i in range(4):
        t = Trace(task=f"t{i}", model="m")
        t.add(Step(kind="tool_call", tool="search", result="ok"))
        t.add(Step(kind="tool_call", tool="flaky-api",
                   result="err", error="timeout"))
        t.success = True
        store.save(t)
    rows, kind = grade_store(store, kind="tool")
    assert kind == "tool"
    by = {r["subject"]: r for r in rows}
    assert by["search"]["grade"] == "A"  # 0 errors / 4 calls
    assert by["flaky-api"]["discipline"] == "F"  # 4/4 errors
    one, _ = grade_store(store, kind="tool", subject="search")
    assert len(one) == 1 and one[0]["subject"] == "search"
    with pytest.raises(KeyError, match="no tool"):
        grade_store(store, kind="tool", subject="ghost")
    with pytest.raises(KeyError, match="no agent"):
        grade_store(store, subject="ghost")


def test_empty_store_prose(tmp_path):
    store = TraceStore(tmp_path)
    rows, kind = grade_store(store)
    assert rows == []
    assert "nothing to grade" in render_grades(rows, kind=kind)


def test_cli_json_and_prose(tmp_path, capsys):
    store = TraceStore(tmp_path)
    _seed(store, "good-bot", 10, fail_idx=(9,))
    args = argparse.Namespace(store=str(tmp_path), agent=None,
                              tool=None, **{"json": True})
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        assert cmd_grade(args) == 0
    payload = json.loads(buf.getvalue())
    assert payload["kind"] == "agent"
    assert payload["grades"][0]["subject"] == "good-bot"
    args = argparse.Namespace(store=str(tmp_path), agent=None,
                              tool=None, **{"json": False})
    assert cmd_grade(args) == 0
    assert "grades" in capsys.readouterr().out


def test_cli_unknown_subject_refuses(tmp_path, capsys):
    TraceStore(tmp_path)
    args = argparse.Namespace(store=str(tmp_path), agent="ghost",
                              tool=None, **{"json": False})
    assert cmd_grade(args) == 2
    capsys.readouterr()


def test_mcp_grade(tmp_path):
    store = TraceStore(tmp_path)
    _seed(store, "good-bot", 10, fail_idx=(9,))
    payload = _tool_grade(ServerContext(str(tmp_path)), {})
    assert payload["kind"] == "agent"
    assert payload["grades"][0]["grade"] == "A"
    narrowed = _tool_grade(ServerContext(str(tmp_path)),
                           {"subject": "good-bot"})
    assert len(narrowed["grades"]) == 1
    with pytest.raises(KeyError, match="no agent"):
        _tool_grade(ServerContext(str(tmp_path)),
                    {"subject": "ghost"})
    with pytest.raises(KeyError, match="kind must be"):
        _tool_grade(ServerContext(str(tmp_path)), {"kind": "fleet"})


def test_grade_cards_sort_key_is_total():
    rows = grade_cards([
        {"agent": "f", "traces": 3, "failure_rate": 0.6,
         "errors": 9, "tool_calls": 9, "breached_traces": 1},
        {"agent": "a", "traces": 3, "failure_rate": 0.0,
         "errors": 0, "tool_calls": 9, "breached_traces": 0},
    ])
    assert [r["grade"] for r in rows] == ["A", "F"]
