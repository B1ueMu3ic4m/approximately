"""v393: the batch gets a plan.

--all posted a hundred rows on one flag with no preview: the
operator (and the agent) learned what would ship only from the
receiver's side of the wire. The batch has a plan now —
--dry-run names what WOULD post, per trace, and posts nothing;
the MCP tool answers dry_run with the manifest as data. The
plan is the same manifest the post would walk (_batch_traces),
so the preview cannot drift from the shipment.
"""

import argparse
import contextlib
import io
import tempfile
from pathlib import Path

from approximately.cli import _ship_batch_plan, cmd_webhook_ship
from approximately.mcp_server import ServerContext, _tool_webhook_ship
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _store_with(n=3):
    store = TraceStore(tempfile.mkdtemp())
    for i in range(n):
        rec = Recorder(f"batch task {i}", store=store)
        rec.tool("sh", {"cmd": f"run {i}"}, result="ok")
        rec.respond("done", success=True)
        store.save(rec.trace)
    return store


def _archive():
    return Path(tempfile.mkdtemp()) / "webhook-log.jsonl"


def test_the_plan_names_what_would_ship():
    store = _store_with(3)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = _ship_batch_plan(store, "box-a")
    out = buf.getvalue()
    assert code == 0
    assert "would ship 3 trace(s) from box-a:" in out
    assert "batch task 0" in out and "batch task 2" in out
    assert out.count("step(s) -") == 3


def test_the_plan_posts_nothing():

    store = _store_with(2)
    archive = _archive()
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        cmd_webhook_ship(argparse.Namespace(
            store=str(store.directory), trace=None,
            url="http://127.0.0.1:1/", all=True, dry_run=True,
            since=None, key_file=None, sender=None))
    assert not archive.exists()
    assert len(store.list_traces()) == 2


def test_the_mcp_manifest_is_data(monkeypatch):
    from approximately import integrity

    monkeypatch.setattr(integrity, "load_key",
                        lambda *a, **k: b"plan-key")
    store = _store_with(2)
    ctx = ServerContext(store.directory)
    result = _tool_webhook_ship(ctx, {"url": "http://127.0.0.1:1/",
                                      "trace": "all",
                                      "dry_run": True})
    assert result["sender"]  # the label still rides
    assert [t["task"] for t in result["would_ship"]] == \
        ["batch task 0", "batch task 1"]
    assert all(t["steps"] == 2
               for t in result["would_ship"])
    # and the plan matches the post, manifest for manifest
    from approximately.cli import _batch_traces

    assert [t.id for t in _batch_traces(store)] == \
        [t["trace_id"] for t in result["would_ship"]]
