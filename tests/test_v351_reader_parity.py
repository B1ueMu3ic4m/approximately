"""v351: one reader, four surfaces — the counts must agree.

The receiver's archive is read by /stats (archive_stats), the CLI
`received` door, the MCP inbox tool and the status frame — all on
top of `read_archive`/`archive_stats`. "One reader" is marketing
until a test makes the same store answer all four and demands the
same numbers: rows, the verified split, the kind census.
"""

import argparse
import contextlib
import io
import json
import tempfile

from approximately.cli import _status_payload, cmd_received
from approximately.mcp_server import ServerContext, _tool_inbox
from approximately.receiver import archive_stats
from approximately.store import TraceStore


def _store_with_archive():
    store = TraceStore(tempfile.mkdtemp())
    archive = store.directory / "webhook-log.jsonl"
    rows = [{"received_at": 1.0 + i, "verified": i % 2 == 0,
             "kind": f"k{i % 3}", "payload": {"seq": i}}
            for i in range(7)]
    with archive.open("a", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
        fh.write("garbage line\n")  # malformed: counted, not parsed
    return store


def _stats_shape(archive):
    s = archive_stats(archive)
    return s["rows"], s["verified"], s["unverified"], s["kinds"]


def test_all_four_readers_agree():
    store = _store_with_archive()
    archive = store.directory / "webhook-log.jsonl"

    # reader 1: /stats
    stats = _stats_shape(archive)

    # reader 2: the received door, JSON shape
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        assert cmd_received(argparse.Namespace(
            store=str(store.directory), archive=str(archive),
            limit=0, kind=None, unverified_only=False,
            include_rotated=False, since=None, json=True)) == 0
    received = json.loads(buf.getvalue())

    # reader 3: the MCP inbox
    inbox = _tool_inbox(ServerContext(store.directory), {})

    # reader 4: the status frame
    status = _status_payload(store, store.list_traces(), None)

    assert stats == (received["rows"], received["verified"],
                     received["unverified"], received["kinds"])
    assert (inbox["rows"], inbox["verified"], inbox["unverified"],
            inbox["kinds"]) == stats
    assert len(inbox["recent"]) == 7 and \
        inbox["rows_total"] == 7, \
        "the inbox defaults to a bounded tail (20; 7 fit)"
    assert (status["webhook_inbox"]["rows"],
            status["webhook_inbox"]["verified"],
            status["webhook_inbox"]["unverified"]) == stats[:3]
    assert status["webhook_inbox"]["present"] is True


def test_all_four_agree_on_an_empty_archive():
    store = TraceStore(tempfile.mkdtemp())
    archive = store.directory / "webhook-log.jsonl"
    stats = _stats_shape(archive)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        assert cmd_received(argparse.Namespace(
            store=str(store.directory), archive=str(archive),
            limit=20, kind=None, unverified_only=False,
            include_rotated=False, since=None, json=True)) == 0
    received = json.loads(buf.getvalue())
    inbox = _tool_inbox(ServerContext(store.directory), {})
    status = _status_payload(store, store.list_traces(), None)
    assert stats == (0, 0, 0, {})
    assert (received["rows"], received["verified"]) == (0, 0)
    assert (inbox["rows"], inbox["verified"]) == (0, 0)
    assert status["webhook_inbox"]["present"] is False
