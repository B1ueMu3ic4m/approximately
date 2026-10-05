"""v294: the triage queue — failed runs ranked by postmortem value.

Not every failure deserves the morning's first hour. ``triage`` ranks
the store's failures: novelty of the failure mode dominates (2.0),
tokens burned, agent breadth and recency nudge (1.0/1.0/0.5). Every
row reports its parts; annotated failures are marked or skipped.
"""

import argparse
import json
import time

from approximately.cli import cmd_triage
from approximately.mcp_server import ServerContext, _tool_triage
from approximately.store import TraceStore
from approximately.trace import Step, Trace
from approximately.triage import render_queue, triage_store


def _failed(store, task, result, agents=None, tokens=0,
            age_s=0.0):
    t = Trace(task=task, model="m")
    for agent in agents or [None]:
        t.add(Step(kind="tool_call", tool="sh", agent=agent,
                   result=result, tokens=tokens, latency_ms=10))
    t.add(Step(kind="error", error=result))
    t.success = False
    t.created_at = time.time() - age_s
    store.save(t)
    return t


def _ok(store, task):
    t = Trace(task=task, model="m")
    t.add(Step(kind="tool_call", tool="sh", result="fine"))
    t.success = True
    store.save(t)
    return t


def test_novelty_dominates_and_decays():
    store = TraceStore("/tmp/triage-test-1")  # isolated by caller cwd
    store = TraceStore(store.directory)
    import tempfile

    store = TraceStore(tempfile.mkdtemp())
    _failed(store, "a one", "ERROR special-flavor", age_s=300)
    _failed(store, "b one", "ERROR special-flavor", age_s=200)
    _failed(store, "c one", "ERROR special-flavor", age_s=100)
    rows = triage_store(store)
    assert len(rows) == 3
    assert rows[0].novelty == 1.0
    assert rows[1].novelty == 0.5
    assert rows[2].novelty == 1.0 / 3.0
    assert rows[0].score > rows[1].score > rows[2].score


def test_success_traces_never_rank():
    import tempfile

    store = TraceStore(tempfile.mkdtemp())
    _ok(store, "fine one")
    _ok(store, "fine two")
    assert triage_store(store) == []
    assert "nothing to triage" in render_queue([])


def test_cost_and_blast_break_ties():
    import tempfile

    store = TraceStore(tempfile.mkdtemp())
    now = time.time()
    # same mode, same novelty window position -> cost/blast decide
    t1 = Trace(task="cheap single", model="m")
    t1.add(Step(kind="tool_call", tool="sh", result="ERROR boom",
                tokens=10))
    t1.add(Step(kind="error", error="ERROR boom"))
    t1.success = False
    t1.created_at = now - 90
    store.save(t1)
    t2 = Trace(task="rich multi", model="m")
    t2.add(Step(kind="tool_call", tool="sh", result="ERROR boom",
                tokens=900, agent="planner"))
    t2.add(Step(kind="tool_call", tool="sh", result="ERROR boom",
                tokens=900, agent="worker"))
    t2.add(Step(kind="error", error="ERROR boom"))
    t2.success = False
    t2.created_at = now - 60
    store.save(t2)
    rows = triage_store(store)
    assert rows[0].trace_id == t2.id
    assert rows[0].cost_norm == 1.0 and rows[0].blast_norm == 1.0
    parts = rows[0].to_dict()["parts"]
    assert parts["cost"] == 1.0 and parts["blast"] == 1.0


def test_recency_parts_and_novelty_dominance():
    import tempfile

    store = TraceStore(tempfile.mkdtemp())
    now = time.time()
    for i, age in enumerate((200, 100)):
        t = Trace(task=f"tie {i}", model="m")
        t.add(Step(kind="tool_call", tool="sh", result="ERROR boom",
                   tokens=5))
        t.add(Step(kind="error", error="ERROR boom"))
        t.success = False
        t.created_at = now - age
        store.save(t)
    rows = triage_store(store)
    # parts: the newest row carries recency 1.0, the oldest 0.0
    assert rows[0].recency_norm == 0.0
    assert rows[1].recency_norm == 1.0
    # novelty follows window chronology and dominates recency: the
    # first-seen (older) run keeps the top spot despite recency 0
    assert rows[0].novelty == 1.0 and rows[1].novelty == 0.5
    assert rows[0].score > rows[1].score


def test_annotation_mark_and_skip():
    import tempfile

    store = TraceStore(tempfile.mkdtemp())
    t1 = _failed(store, "marked one", "ERROR boom", age_s=100)
    _failed(store, "fresh one", "ERROR boom", age_s=50)
    store.annotate(t1.id, "dup of yesterday", verdict="confirmed")
    rows = triage_store(store)
    assert [r.annotated for r in rows] == [True, False]
    skipped = triage_store(store, unannotated_only=True)
    assert len(skipped) == 1 and skipped[0].annotated is False


def test_render_queue_prose():
    import tempfile

    store = TraceStore(tempfile.mkdtemp())
    _failed(store, "the failure", "ERROR boom", age_s=10)
    rows = triage_store(store)
    prose = render_queue(rows)
    assert "triage queue (1 failed" in prose
    assert "the failure" in prose
    assert "modes:" in prose


def test_cli_json_and_limit(tmp_path):
    store = TraceStore(tmp_path)
    for i in range(5):
        _failed(store, f"run {i}", "ERROR boom", age_s=100 - i)
    args = argparse.Namespace(store=str(tmp_path), limit=2,
                              since_days=None, unannotated_only=False,
                              **{"json": True})
    import contextlib
    import io

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        assert cmd_triage(args) == 0
    payload = json.loads(buf.getvalue())
    assert payload["total"] == 5
    assert len(payload["queue"]) == 2
    assert set(payload["queue"][0]["parts"]) == {
        "novelty", "cost", "blast", "recency"}


def test_cli_prose_and_window(tmp_path, capsys):
    store = TraceStore(tmp_path)
    _failed(store, "old one", "ERROR boom", age_s=90 * 86400)
    _failed(store, "new one", "ERROR boom", age_s=10)
    args = argparse.Namespace(store=str(tmp_path), limit=20,
                              since_days=7, unannotated_only=False,
                              **{"json": False})
    assert cmd_triage(args) == 0
    out = capsys.readouterr().out
    assert "new one" in out and "old one" not in out
    assert payload_ok(out)


def payload_ok(out: str) -> bool:
    return "triage queue (1 failed" in out


def test_mcp_triage(tmp_path):
    store = TraceStore(tmp_path)
    _failed(store, "queue me", "ERROR boom", age_s=5)
    payload = _tool_triage(ServerContext(str(tmp_path)), {})
    assert payload["total"] == 1
    row = payload["queue"][0]
    assert row["task"] == "queue me"
    assert row["annotated"] is False
    capped = _tool_triage(ServerContext(str(tmp_path)),
                          {"limit": 0})
    assert capped["total"] == 1 and capped["queue"] == []


def test_determinism_on_same_input():
    import tempfile

    store = TraceStore(tempfile.mkdtemp())
    _failed(store, "alpha", "ERROR boom", age_s=10)
    _failed(store, "beta", "ERROR other", age_s=10)
    t1 = [r.to_dict() for r in triage_store(store)]
    t2 = [r.to_dict() for r in triage_store(store)]
    # created_at differs between the two runs' saves; compare shapes
    # and score order stability instead of timestamps
    assert [r["task"] for r in t1] == [r["task"] for r in t2]
