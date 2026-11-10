"""v405: the reports go machine-readable.

The flush and the batch reported in prose — fine for a
terminal, useless for a script or an agent piping results:
exit codes say pass/fail but nothing about WHICH trace failed
or how many attempts it has. `--json` on webhook-ship turns
both reports into data — the flush report carries every kept
row's attempts, the batch report carries per-trace status —
same shapes the MCP tools already answer with, one flag on the
door the cron and the shell already use.
"""

import argparse
import json
import tempfile
from pathlib import Path

from approximately import cli
from approximately.cli import _spool_append, cmd_webhook_ship
from approximately.recorder import Recorder
from approximately.store import TraceStore

KEY = b"json-key"


def _store_with_spool(n=2):
    store = TraceStore(tempfile.mkdtemp())
    rec = Recorder("json report task", store=store)
    rec.tool("sh", {"cmd": "x"}, result="ok")
    rec.respond("done", success=True)
    store.save(rec.trace)
    spool = cli._spool_path(str(store.directory))
    for _ in range(n):
        _spool_append(spool, rec.trace.id,
                      "http://127.0.0.1:1/", "box-a")
    return store, spool, rec.trace.id


def test_the_flush_report_is_json(capsys, monkeypatch):
    from approximately import integrity

    monkeypatch.setattr(integrity, "load_key",
                        lambda *a, **k: KEY)
    store, _spool, tid = _store_with_spool(2)
    code = cmd_webhook_ship(argparse.Namespace(
        store=str(store.directory), trace=None,
        url="http://127.0.0.1:1/", all=False, dry_run=False,
        since=None, key_file=None, sender=None,
        spool=False, flush=True, json=True))
    out = capsys.readouterr().out
    assert code == 1, "kept shipments still fail the flush"
    report = json.loads(out)
    assert report["flushed"] == 0 and report["kept"] == 2
    assert all(r["trace_id"] == tid and r["attempts"] == 1
               for r in report["results"]), \
        "the report carries the per-row attempt count"


def test_the_flush_plan_is_json_too(capsys, monkeypatch):
    from approximately import integrity

    monkeypatch.setattr(integrity, "load_key",
                        lambda *a, **k: KEY)
    store, _spool, _tid = _store_with_spool(1)
    cmd_webhook_ship(argparse.Namespace(
        store=str(store.directory), trace=None,
        url="http://127.0.0.1:1/", all=False, dry_run=True,
        since=None, key_file=None, sender=None,
        spool=False, flush=True, json=True))
    report = json.loads(capsys.readouterr().out)
    assert report["dry_run"] is True
    assert report["results"][0]["would_retry"] is True


def test_the_batch_report_is_json(capsys, monkeypatch):
    from approximately import integrity
    from approximately.receiver import serve

    monkeypatch.setattr(integrity, "load_key",
                        lambda *a, **k: b"mismatched")
    server, _archive, url = None, None, None
    server, state = serve(Path(tempfile.mkdtemp())
                          / "webhook-log.jsonl",
                          key=b"other-key", port=0)
    url = f"http://127.0.0.1:{server.server_address[1]}"
    store = TraceStore(tempfile.mkdtemp())
    rec = Recorder("batch json task", store=store)
    rec.tool("sh", {"cmd": "x"}, result="ok")
    rec.respond("done", success=True)
    store.save(rec.trace)
    try:
        code = cmd_webhook_ship(argparse.Namespace(
            store=str(store.directory), trace=None, url=url,
            all=True, dry_run=False, since=None,
            key_file=None, sender=None, spool=False,
            flush=False, json=True))
        out = capsys.readouterr()
        assert code == 1, "a refused batch fails"
        report = json.loads(out.out)
        assert report["sender"]  # the label rides the report
        assert report["shipped"] == 0 and report["failed"] == 1
        assert report["results"][0]["trace_id"] == rec.trace.id
        assert "401" in report["results"][0]["error"]
        assert state.refused == 1
    finally:
        server.shutdown()
