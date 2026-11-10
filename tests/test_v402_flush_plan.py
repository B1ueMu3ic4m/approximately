"""v402: the flush gets a plan too.

Every mutating door learned plan-first — retention plans, the
import plans, the batch ships a manifest — but the spool's
flush still posted on one flag with no preview: the operator
saw what would retry only from the receiver's side of the
wire. `--flush --dry-run` reads the same queue the flush would
walk and posts nothing (per-row: the id, the recorded URL, the
attempt count); the MCP tool answers flush_dry_run with the
queue as data. Reading is not deciding, even for a retry.
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

KEY = b"plan-key"


def _store_with_spool(n=2):
    store = TraceStore(tempfile.mkdtemp())
    rec = Recorder("flush plan task", store=store)
    rec.tool("sh", {"cmd": "x"}, result="ok")
    rec.respond("done", success=True)
    store.save(rec.trace)
    spool = cli._spool_path(str(store.directory))
    for _ in range(n):
        _spool_append(spool, rec.trace.id,
                      "http://127.0.0.1:1/", "box-a")
    return store, spool, rec.trace.id


def test_the_flush_plan_posts_nothing():
    store, spool, tid = _store_with_spool(2)
    archive = Path(tempfile.mkdtemp()) / "webhook-log.jsonl"
    report = _spool_flush(store, spool, KEY, dry_run=True)
    assert report["dry_run"] is True
    assert report["kept"] == 2 and report["flushed"] == 0
    assert [r["trace_id"] for r in report["results"]] == \
        [tid, tid], "the plan is what the flush would walk"
    assert all(r["would_retry"] for r in report["results"])
    assert not archive.exists(), "a plan posts nothing"
    assert len(_spool_rows(spool)) == 2, \
        "a plan touches the queue's attempts, never"


def test_the_cli_plan_names_rows_and_exits_zero(capsys,
                                                monkeypatch):
    from approximately import integrity

    monkeypatch.setattr(integrity, "load_key",
                        lambda *a, **k: KEY)
    store, _spool, tid = _store_with_spool(1)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = cmd_webhook_ship(argparse.Namespace(
            store=str(store.directory), trace=None,
            url="http://127.0.0.1:1/", all=False, dry_run=True,
            since=None, key_file=None, sender=None,
            spool=False, flush=True))
    out = buf.getvalue()
    assert code == 0
    assert "would retry 1 shipment(s):" in out
    assert tid in out and "(attempts: 0)" in out


def test_the_real_flush_still_works_after_a_plan(monkeypatch):
    from approximately import integrity
    from approximately.receiver import serve

    monkeypatch.setattr(integrity, "load_key",
                        lambda *a, **k: KEY)
    archive = Path(tempfile.mkdtemp()) / "webhook-log.jsonl"
    server, _state = serve(archive, key=KEY, port=0)
    url = f"http://127.0.0.1:{server.server_address[1]}"
    store, spool, tid = _store_with_spool(1)
    try:
        # plan first, post second - the plan cannot drift
        plan = _spool_flush(store, spool, KEY, dry_run=True)
        assert plan["dry_run"] is True
        rows = _spool_rows(spool)
        spool.write_text("".join(
            json.dumps({**r, "url": url}, sort_keys=True) + "\n"
            for r in rows), encoding="utf-8")
        report = _spool_flush(store, spool, KEY)
        assert report["flushed"] == 1
        got = [json.loads(line) for line
               in archive.read_text().splitlines()]
        assert got[0]["payload"]["trace"]["id"] == tid
    finally:
        server.shutdown()


def test_the_mcp_tool_answers_the_queue_as_data(monkeypatch):
    from approximately import integrity

    monkeypatch.setattr(integrity, "load_key",
                        lambda *a, **k: KEY)
    store, spool, tid = _store_with_spool(1)
    ctx = ServerContext(store.directory)
    plan = _tool_webhook_ship(ctx, {"flush": True,
                                    "flush_dry_run": True})
    assert plan["dry_run"] is True
    assert [r["trace_id"] for r in plan["results"]] == [tid]
    assert len(_spool_rows(spool)) == 1, "a data plan posts no"
