"""v315: value-weighted retention.

``clean`` deletes by age alone; retention keeps postmortem value:
successes age out first, failures (and unknown outcomes) live
longer, and the two guards — breach evidence and annotated traces —
veto every retirement, twice (plan and apply). The plan never
deletes; poison is doctor's job and is never touched here.
"""

import argparse
import tempfile
import time

import pytest

from approximately.cli import cmd_retention
from approximately.mcp_server import ServerContext, _tool_retention
from approximately.retention import apply_plan, retention_plan
from approximately.store import TraceStore
from approximately.trace import Step, Trace

# the CLI/MCP doors plan against the real clock; every age in this
# file is "days back from NOW"
NOW = time.time()


def _trace(store, task, success, age_days, breached=False):
    t = Trace(task=task, model="m")
    t.add(Step(kind="tool_call", tool="sh", result="x", tokens=5))
    t.success = success
    t.created_at = NOW - age_days * 86400.0
    if breached:
        t.meta = {"budget": {"exceeded": True}}
    store.save(t)
    return t


def _store():
    return TraceStore(tempfile.mkdtemp())


def test_plan_keeps_value_and_retires_boredom():
    store = _store()
    _trace(store, "old ok", True, 39)
    _trace(store, "old failure", False, 39)
    _trace(store, "fresh ok", True, 2)
    _trace(store, "old unknown", None, 39)
    plan = retention_plan(store, keep_days=7, failure_days=60,
                          now=NOW)
    retired = {r["id"] for r in plan["retire"]}
    by_task = {t.task: t.id for t in store.list_traces()}
    assert by_task["old ok"] in retired
    assert by_task["old failure"] not in retired, \
        "failures live to failure_days"
    assert by_task["fresh ok"] not in retired
    assert by_task["old unknown"] not in retired, \
        "an unknown outcome is a question retention keeps alive"
    why = next(r["why"] for r in plan["retire"])
    assert why == "success past 7d"
    assert plan["kept"]["failure_young"] == 2  # failure + unknown
    assert plan["kept"]["fresh"] == 1


def test_guards_veto_the_retirement():
    store = _store()
    _trace(store, "old breached ok", True, 39, breached=True)
    old_ok = _trace(store, "old annotated ok", True, 39)
    store.annotate(old_ok.id, "postmortemed on tuesday")
    plan = retention_plan(store, keep_days=7, now=NOW)
    assert plan["retire"] == []
    assert plan["kept"]["protected_breached"] == 1
    assert plan["kept"]["protected_annotated"] == 1


def test_poison_is_doctors_job():
    store = _store()
    (store.directory / "poison.json").write_text("{not json",
                                                 encoding="utf-8")
    plan = retention_plan(store, keep_days=7, now=NOW)
    assert plan["retire"] == []
    assert plan["kept"]["unreadable"] == 1
    assert (store.directory / "poison.json").is_file()


def test_apply_rechecks_guards_and_removes_the_rest():
    store = _store()
    a = _trace(store, "old ok one", True, 39)
    b = _trace(store, "old ok two", True, 39)
    _trace(store, "old breached", True, 39, breached=True)
    plan = retention_plan(store, keep_days=7, now=NOW)
    assert {r["id"] for r in plan["retire"]} == {a.id, b.id}
    # evidence appears between plan and apply: the guard holds
    store.annotate(b.id, "someone still needs this")
    assert apply_plan(store, plan) == 1
    remaining = {p.stem for p in store.directory.glob("*.json")}
    assert a.id not in remaining
    assert b.id in remaining


def test_windows_refuse_sub_day():
    store = _store()
    with pytest.raises(ValueError):
        retention_plan(store, keep_days=0)
    with pytest.raises(ValueError):
        retention_plan(store, keep_days=7, failure_days=0)


def test_cli_dry_run_is_the_default(tmp_path, capsys):
    store = _store()
    _trace(store, "old ok", True, 39)
    before = {p.stem for p in store.directory.glob("*.json")}
    args = argparse.Namespace(store=store.directory, keep_days=7,
                              failure_days=None, apply=False,
                              json=False)
    assert cmd_retention(args) == 0
    out = capsys.readouterr().out
    assert "dry run" in out and "retire" in out
    assert {p.stem for p in store.directory.glob("*.json")} == before


def test_cli_apply_and_refusal(tmp_path, capsys):
    store = _store()
    _trace(store, "old ok", True, 39)
    args = argparse.Namespace(store=store.directory, keep_days=7,
                              failure_days=None, apply=True,
                              json=False)
    assert cmd_retention(args) == 0
    assert "removed 1" in capsys.readouterr().out
    assert list(store.directory.glob("*.json")) == []
    args.keep_days = 0
    assert cmd_retention(args) == 2
    assert "keep_days" in capsys.readouterr().err


def test_mcp_plan_only_smoke():
    store = _store()
    _trace(store, "old ok", True, 39)
    ctx = ServerContext(store.directory)
    payload = _tool_retention(ctx, {"keep_days": 7})
    assert len(payload["retire"]) == 1
    assert (store.directory / f"{payload['retire'][0]['id']}"
             ".json").is_file(), "the MCP door never deletes"
    with pytest.raises(KeyError):
        _tool_retention(ctx, {})
