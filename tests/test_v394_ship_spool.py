"""v394: the network being down must not lose the evidence.

A refused shipment died at the door: the error printed, exit
code set, and the operator had to remember the trace id by
hand. --spool queues the refusal (the reference, never the
body — the trace stays the store's to keep honest) and --flush
drains it later: delivered rows leave the queue, traces gone
from the store are reported and dropped, persistent failures
stay with attempts incremented. The MCP tool speaks the same
two moves (spool / flush), so an agent can survive a receiver
reboot too.
"""

import argparse
import contextlib
import io
import json
import tempfile
from pathlib import Path

from approximately import cli
from approximately.cli import _spool_append, _spool_flush, _spool_rows, cmd_webhook_ship
from approximately.mcp_server import ServerContext, _tool_webhook_ship
from approximately.recorder import Recorder
from approximately.store import TraceStore

KEY = b"spool-key"


def _store_with(n=2):
    store = TraceStore(tempfile.mkdtemp())
    ids = []
    for i in range(n):
        rec = Recorder(f"spool task {i}", store=store)
        rec.tool("sh", {"cmd": f"run {i}"}, result="ok")
        rec.respond("done", success=True)
        store.save(rec.trace)
        ids.append(rec.trace.id)
    return store, ids


def _receiver(key=KEY, port=0):
    from approximately.receiver import serve

    archive = Path(tempfile.mkdtemp()) / "webhook-log.jsonl"
    server, _state = serve(archive, key=key, port=port)
    return server, archive, f"http://127.0.0.1:{server.server_address[1]}"


def test_a_refused_batch_shipment_queues():
    server, _archive, url = _receiver(key=b"other-key")
    store, ids = _store_with(2)
    try:
        spool = cli._spool_path(str(store.directory))
        batch = cli._ship_batch(store, url, KEY, "box-a")
        for r in batch["results"]:
            if "error" in r:
                _spool_append(spool, r["trace_id"], url, "box-a")
        rows = _spool_rows(spool)
        assert [r["trace_id"] for r in rows] == ids
        assert all(r["attempts"] == 0 for r in rows)
    finally:
        server.shutdown()


def test_the_flush_delivers_when_the_receiver_returns():
    dead = "http://127.0.0.1:1/"
    store, ids = _store_with(2)
    spool = cli._spool_path(str(store.directory))
    _spool_append(spool, ids[0], dead, "box-a")
    _spool_append(spool, ids[1], dead, "box-a")
    server, archive, url = _receiver()
    try:
        # the queue still points at the dead URL: the flush
        # re-ships to the RECORDED url, so rewrite it to the
        # live one the way an operator's config change would
        rows = _spool_rows(spool)
        spool.write_text("".join(
            json.dumps({**r, "url": url}, sort_keys=True) + "\n"
            for r in rows), encoding="utf-8")
        report = _spool_flush(store, spool, KEY)
        assert report["flushed"] == 2 and report["kept"] == 0
        got = [json.loads(line) for line
               in archive.read_text().splitlines()]
        assert {r["payload"]["trace"]["id"] for r in got} == \
            set(ids)
        assert not _spool_rows(spool), \
            "delivered rows leave the queue"
    finally:
        server.shutdown()


def test_a_persistent_failure_stays_with_attempts():
    store, ids = _store_with(1)
    spool = cli._spool_path(str(store.directory))
    _spool_append(spool, ids[0], "http://127.0.0.1:1/", "box-a")
    report = _spool_flush(store, spool, KEY)
    assert report["flushed"] == 0 and report["kept"] == 1
    rows = _spool_rows(spool)
    assert rows[0]["attempts"] == 1
    _spool_flush(store, spool, KEY)
    assert _spool_rows(spool)[0]["attempts"] == 2, \
        "every flush counts"


def test_a_trace_gone_from_the_store_drops():
    store, _ids = _store_with(1)
    spool = cli._spool_path(str(store.directory))
    _spool_append(spool, "vanished-id", "http://127.0.0.1:1/",
                  "box-a")
    report = _spool_flush(store, spool, KEY)
    assert report["dropped"] == 1
    assert not _spool_rows(spool)


def test_the_cli_flush_reports_and_exits(monkeypatch):
    from approximately import integrity

    monkeypatch.setattr(integrity, "load_key",
                        lambda *a, **k: KEY)
    store, ids = _store_with(1)
    spool = cli._spool_path(str(store.directory))
    _spool_append(spool, ids[0], "http://127.0.0.1:1/", "box-a")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = cmd_webhook_ship(argparse.Namespace(
            store=str(store.directory), trace=None,
            url="http://127.0.0.1:1/", all=False, dry_run=False,
            since=None, key_file=None, sender=None,
            spool=False, flush=True))
    out = buf.getvalue()
    assert code == 1, "kept shipments fail the flush"
    assert "flushed 0 shipment(s) (1 kept" in out


def test_the_mcp_tool_spools_and_flushes(monkeypatch):
    from approximately import integrity

    monkeypatch.setattr(integrity, "load_key",
                        lambda *a, **k: KEY)
    server, _archive, url = _receiver(key=b"mismatch")
    store, _ids = _store_with(2)
    try:
        ctx = ServerContext(store.directory)
        batch = _tool_webhook_ship(ctx, {
            "url": url, "trace": "all", "spool": True})
        assert batch["spooled"] == 2, \
            "every refusal queues under a key mismatch"
        # the receiver comes around: same server, matching key
        server.shutdown()
        server2, archive2, url2 = _receiver(key=KEY)
        try:
            rows = _spool_rows(cli._spool_path(store.directory))
            spool = cli._spool_path(store.directory)
            spool.write_text("".join(
                json.dumps({**r, "url": url2}, sort_keys=True)
                + "\n" for r in rows), encoding="utf-8")
            report = _tool_webhook_ship(ctx, {"url": url2,
                                              "flush": True})
            assert report["flushed"] == 2
            got = [json.loads(line) for line
                   in archive2.read_text().splitlines()]
            assert len(got) == 2
        finally:
            server2.shutdown()
    finally:
        server.shutdown()
