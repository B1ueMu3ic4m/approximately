"""v372: the reader's filters reach every surface.

The parity audit found two holes left from v371: the MCP inbox
took no ``since`` (the CLI's --since had no twin), and the status
frame's webhook_inbox carried the verified split but dropped the
kind census the digest and /stats both answer. One reader means
one answer set: every surface now carries the same filters and
the same census, formatted the same way.
"""

import argparse
import contextlib
import io
import json
import tempfile
import time

import pytest

from approximately.cli import _status_payload, cmd_received
from approximately.mcp_server import ServerContext, _tool_inbox
from approximately.receiver import archive_stats
from approximately.store import TraceStore


def _store_with_archive():
    store = TraceStore(tempfile.mkdtemp())
    archive = store.directory / "webhook-log.jsonl"
    now = time.time()
    rows = [{"received_at": now - 50, "verified": True,
             "kind": "trace_failure", "payload": {}},
            {"received_at": now - 100, "verified": False,
             "kind": "spool", "payload": {}},
            {"received_at": now - 9000, "verified": True,
             "kind": "spool", "payload": {}}]
    with archive.open("a", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
    return store, archive, now


def test_mcp_inbox_since_filters_like_the_cli():
    store, _archive, now = _store_with_archive()
    hits = _tool_inbox(ServerContext(store.directory),
                       {"since": now - 120})
    assert [r["kind"] for r in hits["recent"]] == \
        ["trace_failure", "spool"], \
        "the 9000-second-old row is out of scope"
    fresh = _tool_inbox(ServerContext(store.directory),
                        {"since": now - 70})
    assert [r["kind"] for r in fresh["recent"]] == \
        ["trace_failure"], "only the 50-second-old row is in scope"


def test_mcp_inbox_refuses_hostile_since_at_the_boundary():
    store, _archive, _now = _store_with_archive()
    ctx = ServerContext(store.directory)
    with pytest.raises(ValueError):
        _tool_inbox(ctx, {"since": "30m"})
    with pytest.raises(ValueError):
        _tool_inbox(ctx, {"since": True})


def test_status_frame_carries_the_kind_census():
    store, archive, _now = _store_with_archive()
    status = _status_payload(store, store.list_traces(), None)
    stats = archive_stats(archive)
    assert status["webhook_inbox"]["kinds"] == stats["kinds"], \
        "the frame answers the same census /stats answers"


def test_the_frame_renders_the_census_like_the_digest():
    store, _archive, _now = _store_with_archive()
    from approximately.cli import _render_status
    text = _render_status(argparse.Namespace(
        store=str(store.directory), since=None, digest_dir=None,
        json=False, prices=None, spend_ceiling=None,
        failure_budget=None))
    assert "    kinds: spool x2, trace_failure x1" in text, \
        "alphabetical, the digest's exact format"


def test_the_one_shot_reader_still_agrees_with_every_surface():
    # the v351 parity pin, extended to the census
    store, archive, _now = _store_with_archive()
    stats = archive_stats(archive)
    status = _status_payload(store, store.list_traces(), None)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        assert cmd_received(argparse.Namespace(
            store=str(store.directory), archive=str(archive),
            limit=0, kind=None, unverified_only=False,
            include_rotated=False, since=None, grep=None,
            json=True)) == 0
    received = json.loads(buf.getvalue())
    inbox = _tool_inbox(ServerContext(store.directory), {})
    assert (status["webhook_inbox"]["kinds"] == stats["kinds"]
            == received["kinds"] == inbox["kinds"])
