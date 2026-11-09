"""v388: the inbox knows who shipped it.

The channel moved evidence but not identity: every trace_ship
row arrived anonymous, so a receiver serving three boxes read
one undifferentiated pile. The ship door labels its rows now
(--from, default this host's hostname), the census counts
shippers by label (only a non-empty string counts — anything
else is noise, not a name), the reader narrows by label
(--sender on the door, sender on the tool), and the status
frame names who shipped — the ops story works without anyone
remembering a flag.
"""

import argparse
import io
import json
import socket
import tempfile
from pathlib import Path

import pytest

from approximately.cli import _ship_core, cmd_received
from approximately.mcp_server import ServerContext, _tool_inbox, _tool_webhook_ship
from approximately.receiver import archive_stats, filtered_stats
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _ship_row(sender, verified=True, at=1.0, tid=None):
    return {"received_at": at, "verified": verified,
            "kind": "trace_ship",
            "payload": {"trace": {"id": tid or f"t{at}",
                                  "task": "shipped", "steps": []},
                        "sender": sender}}


def _store_with(rows):
    store = TraceStore(tempfile.mkdtemp())
    archive = store.directory / "webhook-log.jsonl"
    with archive.open("a", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, sort_keys=True) + "\n")
    return store, archive


def _trace_in(store, task="shipped from here"):
    rec = Recorder(task, store=store)
    rec.tool("sh", {"cmd": "deploy"}, result="ok")
    rec.respond("done", success=True)
    store.save(rec.trace)
    return rec.trace


def _receiver(key=b"who-ships"):
    from approximately.receiver import serve

    archive = Path(tempfile.mkdtemp()) / "webhook-log.jsonl"
    server, _state = serve(archive, key=key, port=0)
    port = server.server_address[1]
    return server, archive, f"http://127.0.0.1:{port}"


def test_the_ship_door_labels_its_rows():
    server, archive, url = _receiver()
    store = TraceStore(tempfile.mkdtemp())
    trace = _trace_in(store, "labeled shipment")
    try:
        result = _ship_core(str(store.directory), trace.id, url,
                            b"who-ships", sender="box-a")
        assert result["sender"] == "box-a"
        row = json.loads(archive.read_text().splitlines()[0])
        assert row["payload"]["sender"] == "box-a", \
            "the label rode the signed body"
    finally:
        server.shutdown()


def test_the_default_label_is_this_host():
    server, archive, url = _receiver()
    store = TraceStore(tempfile.mkdtemp())
    trace = _trace_in(store, "default label")
    try:
        result = _ship_core(str(store.directory), trace.id, url,
                            b"who-ships")
        assert result["sender"] == socket.gethostname()
        row = json.loads(archive.read_text().splitlines()[0])
        assert row["payload"]["sender"] == socket.gethostname()
    finally:
        server.shutdown()


def test_the_census_counts_shippers_by_label():
    _store, archive = _store_with([
        _ship_row("box-a", at=1.0),
        _ship_row("box-a", at=2.0),
        _ship_row("box-b", at=3.0),
    ])
    stats = archive_stats(archive)
    assert stats["senders"] == {"box-a": 2, "box-b": 1}


def test_only_a_string_counts_as_a_shipper():
    _store, archive = _store_with([
        _ship_row(123, at=1.0),
        _ship_row("", at=2.0),
        _ship_row(None, at=3.0),
        {"received_at": 4.0, "verified": True,
         "kind": "ping"},  # no payload at all
    ])
    stats = archive_stats(archive)
    assert stats["senders"] == {}, \
        "noise is not a name; the census never crashes"
    assert stats["rows"] == 4


def test_the_scoped_census_follows_the_filter():
    _store, archive = _store_with([
        _ship_row("box-a", at=1.0, tid="a1"),
        _ship_row("box-b", at=2.0, tid="b1"),
    ])
    stats = filtered_stats(archive, kind="trace_ship")
    assert stats["senders"] == {"box-a": 1, "box-b": 1}, \
        "the scoped census follows the matching rows"
    from approximately.receiver import read_archive

    narrowed = read_archive(archive, sender="box-a")
    assert [r["payload"]["trace"]["id"] for r in
            narrowed["recent"]] == ["a1"]
    assert narrowed["senders"] == {"box-a": 1, "box-b": 1}, (
        "the census describes the whole log; the rows describe "
        "the filter")


def test_the_received_door_filters_and_prints(capsys):
    store, _archive = _store_with([
        _ship_row("box-a", at=1.0),
        _ship_row("box-b", at=2.0),
    ])
    cmd_received(argparse.Namespace(
        store=str(store.directory), archive=None, limit=20,
        kind=None, sender="box-a", unverified_only=False,
        include_rotated=False, since=None, grep=None,
        follow=False, interval=1.0, max_passes=0, json=False))
    out = capsys.readouterr().out
    assert "from box-a: 1" in out, "the census names shippers"
    assert "from box-b: 1" in out, \
        "stats describe the log; rows describe the filter"
    assert out.count("shipped") == 1, \
        "the sender filter narrows the rows"


def test_the_mcp_ship_tool_takes_the_label(monkeypatch):
    from approximately import integrity

    monkeypatch.setattr(integrity, "load_key",
                        lambda *a, **k: b"who-ships")
    server, _archive, url = _receiver()
    store = TraceStore(tempfile.mkdtemp())
    trace = _trace_in(store, "tool-labeled")
    try:
        ctx = ServerContext(store.directory)
        result = _tool_webhook_ship(ctx, {
            "url": url, "trace": trace.id, "sender": "box-mcp"})
        assert result["sender"] == "box-mcp"
        with pytest.raises(ValueError, match="must be a string"):
            _tool_webhook_ship(ctx, {"url": url,
                                     "sender": 42})
    finally:
        server.shutdown()


def test_the_mcp_inbox_tool_filters_by_sender():
    store, _archive = _store_with([
        _ship_row("box-a", at=1.0),
        _ship_row("box-b", at=2.0),
    ])
    ctx = ServerContext(store.directory)
    inbox = _tool_inbox(ctx, {"sender": "box-a"})
    assert len(inbox["recent"]) == 1
    assert inbox["recent"][0]["payload"]["sender"] == "box-a"
    with pytest.raises(ValueError, match="must be a string"):
        _tool_inbox(ctx, {"sender": ["box-a"]})


def test_the_frame_names_who_shipped():
    from approximately.cli import _write_inbox_lines

    buf = io.StringIO()
    _write_inbox_lines(buf, {"present": True, "rows": 3,
                             "verified": 3, "unverified": 0,
                             "kinds": {"trace_ship": 3},
                             "senders": {"box-b": 1,
                                         "box-a": 2}})
    assert "    from: box-a x2, box-b x1" in buf.getvalue()
    buf = io.StringIO()
    _write_inbox_lines(buf, {"present": True, "rows": 1,
                             "verified": 1, "unverified": 0,
                             "kinds": {"ping": 1},
                             "senders": {}})
    assert "from:" not in buf.getvalue(), \
        "no zero parade for shippers that never labeled"
