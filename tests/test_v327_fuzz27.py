"""Fuzz 27: poison in the newest surfaces — fleet digest, trend,
since-days, worklist.

The chain contract keeps widening with the surface: the fleet
brief ranks stores by pain (a poisoned store must not poison the
ranking), the trend reads two windows of hostile clocks, the
worklist renders only what triage lets through, and the widened
arrival window counts what exists without crashing on what
doesn't.
"""

import json
import tempfile
import time

from approximately.digest import build_digest, build_fleet_digest, render_fleet_markdown
from approximately.grade import grade_trend
from approximately.handoff import worklist
from approximately.mcp_server import ServerContext, _tool_digest
from approximately.store import TraceStore
from approximately.trace import Step, Trace


def _trace(store, task, success, age_days, agent=None):
    t = Trace(task=task, model="m")
    t.add(Step(kind="tool_call", tool="sh", result="x" * 50,
               tokens=10 ** 6, agent=agent))
    t.success = success
    t.created_at = time.time() - age_days * 86400.0
    store.save(t)
    return t


def _poison_tasks():
    return [
        "deploy with \x00",
        "```fence\nrun\n```",
        "# injected header",
        "y" * 8_000,
        "task \u200b with zero width",
    ]


def test_fleet_digest_ranks_poisoned_stores_without_crashing():
    stores = []
    for _n in range(3):
        s = TraceStore(tempfile.mkdtemp())
        for i, task in enumerate(_poison_tasks()):
            _trace(s, task, i % 2 == 1, i * 0.1)
        stores.append(s)
    payload = build_fleet_digest(stores)
    page = render_fleet_markdown(payload)
    assert page.startswith("# fleet digest — 3 store(s)")
    assert "```" not in page
    json.dumps(payload, default=str)


def test_mcp_fleet_digest_stays_serializable():
    s = TraceStore(tempfile.mkdtemp())
    for i, task in enumerate(_poison_tasks()):
        _trace(s, task, i % 2 == 0, i * 0.1)
    payload = _tool_digest(ServerContext(s.directory),
                           {"triage_top": 2})
    json.dumps(payload, default=str)


def test_trend_over_hostile_clocks():
    s = TraceStore(tempfile.mkdtemp())
    _trace(s, "future run", True, -100)      # created_at in the future
    _trace(s, "ancient run", False, 400)     # outside both windows
    _trace(s, "this week ok", True, 1, agent="bot")
    _trace(s, "this week fail", False, 2, agent="bot")
    trend = grade_trend(s)
    subjects = {r["subject"] for r in trend["subjects"]}
    assert "bot" in subjects
    assert trend["this_week_traces"] >= 2


def test_widened_window_over_sparse_store():
    s = TraceStore(tempfile.mkdtemp())
    _trace(s, "one old ok", True, 5)
    payload = build_digest(s, since_days=7)
    assert payload["arrivals"]["ok"] == 1
    assert payload["arrivals"]["failed"] == 0
    assert payload["arrivals"]["window_days"] == 7


def test_worklist_over_hostile_queue():
    s = TraceStore(tempfile.mkdtemp())
    for task in _poison_tasks():
        _trace(s, task, False, 0.2)
    page = worklist(s, limit=10)
    assert page.count("# Handoff:") == len(_poison_tasks())
    # the structural invariant: no line may OPEN a code fence —
    # backticks inside a collapsed title are literal text, never
    # a fence boundary
    for line in page.splitlines():
        assert not line.startswith("```"), line[:40]
