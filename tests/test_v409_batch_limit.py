"""v409: --limit — the newest N, not a random slice.

--since scoped the batch by age, but "sync just the latest K
runs" had no answer: a busy store's newest ten sat inside a
thousand-row manifest, and shipping the whole history to save
ten was the only move. --limit keeps the newest N — applied
AFTER the oldest-first sort, so it is the newest of the window
(not a random slice), it composes with --since, it rides the
plan (--dry-run shows the same list the post walks), and the
MCP tool answers limit in both the manifest and the batch.
"""

import tempfile

import pytest

from approximately.cli import _batch_traces, _ship_batch_plan
from approximately.mcp_server import ServerContext, _tool_webhook_ship
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _store_with(n=5):
    store = TraceStore(tempfile.mkdtemp())
    ids = []
    for i in range(n):
        rec = Recorder(f"limit task {i}", store=store)
        rec.tool("sh", {"cmd": f"run {i}"}, result="ok")
        rec.respond("done", success=True)
        store.save(rec.trace)
        ids.append(rec.trace.id)
    return store, ids


def test_limit_keeps_the_newest_of_the_sorted_manifest():
    store, ids = _store_with(5)
    manifest = _batch_traces(store, limit=2)
    assert [t.id for t in manifest] == ids[-2:], \
        "the newest two, still oldest-first between themselves"


def test_limit_zero_ships_nothing():
    store, _ids = _store_with(3)
    assert _batch_traces(store, limit=0) == [], \
        "limit 0 is an honest empty manifest"


def test_limit_composes_with_since():
    import time as _time

    store = TraceStore(tempfile.mkdtemp())
    ids = []
    old = Recorder("old task", store=store)
    old.tool("sh", {"cmd": "x"}, result="ok")
    old.respond("done", success=True)
    old.trace.created_at = _time.time() - 30 * 86400
    store.save(old.trace, stamp=False)
    for i in range(3):
        rec = Recorder(f"fresh {i}", store=store)
        rec.tool("sh", {"cmd": "y"}, result="ok")
        rec.respond("done", success=True)
        store.save(rec.trace)
        ids.append(rec.trace.id)
    manifest = _batch_traces(store, since_days=7, limit=2)
    assert [t.id for t in manifest] == ids[-2:], \
        "the newest two of the window"


def test_the_plan_shows_the_same_list_the_post_walks():
    store, ids = _store_with(4)
    buf = _plan_lines(store, limit=2)
    assert "would ship 2 trace(s)" in buf
    # the plan cannot drift from the post
    assert [t.id for t in _batch_traces(store, limit=2)] == \
        ids[-2:]


def _plan_lines(store, limit=None):
    import contextlib
    import io

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        _ship_batch_plan(store, "box-a", limit=limit)
    return buf.getvalue()


def test_the_mcp_tool_takes_limit(monkeypatch):
    from approximately import integrity

    monkeypatch.setattr(integrity, "load_key",
                        lambda *a, **k: b"limit-key")
    store, ids = _store_with(3)
    ctx = ServerContext(store.directory)
    manifest = _tool_webhook_ship(ctx, {"url": "http://x",
                                        "trace": "all",
                                        "dry_run": True,
                                        "limit": 2})
    assert [t["trace_id"] for t in manifest["would_ship"]] == \
        ids[-2:]
    with pytest.raises(ValueError, match="non-negative"):
        _tool_webhook_ship(ctx, {"url": "http://x",
                                 "trace": "all", "limit": -1})
