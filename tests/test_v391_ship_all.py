"""v391: one box's history becomes another box's inbox.

webhook-ship moved ONE trace per call: syncing a box to a
collector meant a shell loop over trace ids, and an agent with
an MCP client had no way to do it at all. --all ships the whole
store (oldest first, --since scopes the window), one trace at a
time through the same _ship_one mechanics — and a refused trace
never stops the ones after it: each row is independent
evidence, so the batch reports per-trace status instead of
dying on the first problem. trace: "all" is the agent's spelling
of the same move. The batch carries the sender label too.
"""

import json
import tempfile
from pathlib import Path

import pytest

from approximately import cli
from approximately.cli import _ship_batch, cmd_webhook_ship
from approximately.mcp_server import ServerContext, _tool_webhook_ship
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _store_with(n=3):
    store = TraceStore(tempfile.mkdtemp())
    ids = []
    for i in range(n):
        rec = Recorder(f"batch task {i}", store=store)
        rec.tool("sh", {"cmd": f"run {i}"}, result="ok")
        rec.respond("done", success=True)
        store.save(rec.trace)
        ids.append(rec.trace.id)
    return store, ids


def _receiver(key=b"batch-key"):
    from approximately.receiver import serve

    archive = Path(tempfile.mkdtemp()) / "webhook-log.jsonl"
    server, _state = serve(archive, key=key, port=0)
    port = server.server_address[1]
    return server, archive, f"http://127.0.0.1:{port}"


def test_the_batch_ships_the_whole_store():
    server, archive, url = _receiver()
    store, ids = _store_with(3)
    try:
        batch = _ship_batch(store, url, b"batch-key",
                            "box-batch")
        assert batch["shipped"] == 3 and batch["failed"] == 0
        # order is oldest-first where the store knows it; on
        # Windows coarse clocks tie and the order is the store's
        # to break — every trace shipping is the promise
        assert {r["trace_id"] for r in batch["results"]} == \
            set(ids)
        rows = [json.loads(line)
                for line in archive.read_text().splitlines()]
        assert {r["payload"]["trace"]["id"] for r in rows} == \
            set(ids)
        assert len(rows) == 3
        assert all(r["payload"]["sender"] == "box-batch"
                   for r in rows), "the label rides every row"
    finally:
        server.shutdown()


def test_a_refused_trace_never_stops_the_batch(monkeypatch):
    server, _archive, url = _receiver()
    store, ids = _store_with(3)
    real = cli._ship_one

    def flaky(store, trace, url_, key, sender):
        if trace.id == ids[1]:
            raise ValueError("ship NOT accepted: HTTP 401 "
                             "(signature refused)")
        return real(store, trace, url_, key, sender)

    monkeypatch.setattr(cli, "_ship_one", flaky)
    try:
        batch = _ship_batch(store, url, b"batch-key", "box-batch")
        assert batch["shipped"] == 2 and batch["failed"] == 1
        assert batch["results"][1]["trace_id"] == ids[1]
        assert "401" in batch["results"][1]["error"]
    finally:
        server.shutdown()


def test_the_since_window_scopes_the_batch():
    import time as _time

    server, _archive, url = _receiver()
    store = TraceStore(tempfile.mkdtemp())
    old = Recorder("old recording", store=store)
    old.tool("sh", {"cmd": "x"}, result="ok")
    old.respond("done", success=True)
    old.trace.created_at = _time.time() - 30 * 86400
    store.save(old.trace, stamp=False)
    fresh = Recorder("fresh recording", store=store)
    fresh.tool("sh", {"cmd": "y"}, result="ok")
    fresh.respond("done", success=True)
    store.save(fresh.trace)
    try:
        batch = _ship_batch(store, url, b"batch-key",
                            "box-batch", since_days=7)
        assert [r["trace_id"] for r in batch["results"]] == \
            [fresh.trace.id], "the 30-day-old trace stays home"
    finally:
        server.shutdown()


def test_the_cli_door_reports_per_trace(capsys, monkeypatch):
    from approximately import integrity

    monkeypatch.setattr(integrity, "load_key",
                        lambda *a, **k: b"batch-key")
    server, _archive, url = _receiver()
    store, _ids = _store_with(2)
    import argparse

    try:
        code = cmd_webhook_ship(argparse.Namespace(
            store=str(store.directory), trace=None, url=url,
            all=True, since=None, key_file=None, sender=None))
        out = capsys.readouterr()
        assert code == 0
        assert "shipped 2 trace(s) from" in out.out
    finally:
        server.shutdown()


def test_no_trace_and_no_all_is_a_refusal(capsys, monkeypatch):
    from approximately import integrity

    monkeypatch.setattr(integrity, "load_key",
                        lambda *a, **k: b"batch-key")
    store, _ids = _store_with(1)
    import argparse

    code = cmd_webhook_ship(argparse.Namespace(
        store=str(store.directory), trace=None, url="http://x",
        all=False, since=None, key_file=None, sender=None))
    out = capsys.readouterr()
    assert code == 2
    assert "--all" in out.err, "the refusal names the batch door"


def test_the_mcp_tool_ships_all(monkeypatch):
    from approximately import integrity

    monkeypatch.setattr(integrity, "load_key",
                        lambda *a, **k: b"batch-key")
    server, archive, url = _receiver()
    store, _ids = _store_with(2)
    try:
        ctx = ServerContext(store.directory)
        result = _tool_webhook_ship(ctx, {"url": url,
                                          "trace": "all",
                                          "sender": "box-mcp"})
        assert result["shipped"] == 2 and result["failed"] == 0
        rows = [json.loads(line)
                for line in archive.read_text().splitlines()]
        assert {r["payload"]["sender"] for r in rows} == \
            {"box-mcp"}
    finally:
        server.shutdown()


def test_hostile_args_still_refused(monkeypatch):
    from approximately import integrity

    monkeypatch.setattr(integrity, "load_key",
                        lambda *a, **k: b"batch-key")
    store, _ids = _store_with(1)
    ctx = ServerContext(store.directory)
    with pytest.raises(ValueError, match="url is required"):
        _tool_webhook_ship(ctx, {"trace": "all"})
