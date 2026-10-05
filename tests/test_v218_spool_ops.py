"""v218: spool ops — doctor checks it, agents can drive it.

The spool round shipped the watcher; this round gives the two other
surfaces their handle on it: `doctor --spool DIR` reports pending
files and the ones no pass could parse (they stay put by design, so
they count against health), and MCP gains `spool_once` so an agent
can run an ingest pass itself.
"""

import argparse
import json
from pathlib import Path

from approximately.cli import cmd_doctor
from approximately.doctor import doctor
from approximately.mcp_server import ServerContext, handle_request
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _write_run(store, task, success=True):
    # serialized only: the store must learn this run from the spool
    rec = Recorder(task, save=False)
    rec.tool("shell", {"cmd": "ls"}, result="ok")
    rec.respond("done", success=success)
    return rec.trace.to_dict()


def test_doctor_spool_reports_unparsed(tmp_path):
    store = TraceStore(tmp_path / "s")
    spool = tmp_path / "spool"
    spool.mkdir()
    (spool / "good.jsonl").write_text(
        json.dumps(_write_run(store, "fine")) + "\n", encoding="utf-8")
    (spool / "junk.json").write_text("{ not json", encoding="utf-8")
    report = doctor(store.directory, spool_dir=spool)
    assert report.spool_dir == str(spool)
    assert report.spool_pending == 2
    assert report.spool_unparsed == ["junk.json"]
    assert report.healthy is False
    text = report.render()
    assert "spool" in text
    assert "unparsed: junk.json" in text


def test_doctor_spool_healthy_when_clean(tmp_path):
    store = TraceStore(tmp_path / "s")
    spool = tmp_path / "spool"
    spool.mkdir()
    report = doctor(store.directory, spool_dir=spool)
    assert report.spool_pending == 0
    assert report.spool_unparsed == []
    assert report.healthy is True


def test_cli_doctor_spool_json(tmp_path, capsys):
    store = TraceStore(tmp_path / "s")
    spool = tmp_path / "spool"
    spool.mkdir()
    (spool / "junk.json").write_text("garbage", encoding="utf-8")
    args = argparse.Namespace(store=str(store.directory),
                              digest_dir=None, fix=False,
                              judge_cache=None, spool=str(spool),
                              json=True)
    assert cmd_doctor(args) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["spool_pending"] == 1
    assert payload["spool_unparsed"] == ["junk.json"]
    assert payload["healthy"] is False


def test_mcp_spool_once(tmp_path):
    store = TraceStore(tmp_path / "s")
    spool = tmp_path / "spool"
    spool.mkdir()
    (spool / "a.jsonl").write_text(
        json.dumps(_write_run(store, "spooled once")) + "\n",
        encoding="utf-8")
    payload = handle_request({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "spool_once",
                   "arguments": {"store": str(store.directory),
                                 "dir": str(spool)}},
    }, ServerContext(str(store.directory)))
    result = json.loads(payload["result"]["content"][0]["text"])
    assert result["imported"] == 1
    assert result["archived"] == 1
    assert len(store.list_traces()) == 1


def test_mcp_spool_once_dry_run_touches_nothing(tmp_path):
    store = TraceStore(tmp_path / "s")
    spool = tmp_path / "spool"
    spool.mkdir()
    (spool / "a.jsonl").write_text(
        json.dumps(_write_run(store, "dry")) + "\n", encoding="utf-8")
    payload = handle_request({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "spool_once",
                   "arguments": {"store": str(store.directory),
                                 "dir": str(spool),
                                 "dry_run": True}},
    }, ServerContext(str(store.directory)))
    json.loads(payload["result"]["content"][0]["text"])
    assert (spool / "a.jsonl").exists()
    assert len(store.list_traces()) == 0


def test_mcp_spool_once_missing_dir_is_tool_error(tmp_path):
    payload = handle_request({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "spool_once",
                   "arguments": {"dir": str(tmp_path / "nope")}},
    }, ServerContext(str(tmp_path / "s")))
    assert payload["result"]["isError"] is True


def test_tool_inventory_grew_to_36():
    from approximately.mcp_server import _TOOLS

    assert len(_TOOLS) == 41
    names = {t["name"] for t in _TOOLS}
    assert "spool_once" in names


def test_otlp_resource_attrs_reach_meta(tmp_path):
    from approximately.importer import otlp_to_traces

    document = {"resourceSpans": [{
        "resource": {"attributes": [
            {"key": "service.name",
             "value": {"stringValue": "payments-bot"}},
            {"key": "deployment.environment",
             "value": {"stringValue": "prod"}},
        ]},
        "scopeSpans": [{"spans": [
            {"traceId": "a" * 32, "spanId": "1" * 16,
             "parentSpanId": "", "name": "run"},
        ]}],
    }]}
    traces, malformed, _seen, truncated = otlp_to_traces(document)
    assert (malformed, truncated) == (0, 0)
    meta = traces[0].meta
    assert meta["attr.service.name"] == "payments-bot"
    assert meta["attr.deployment.environment"] == "prod"


def test_own_resource_marker_does_not_reach_meta(tmp_path):
    # byte closure: our service.name must not become run metadata
    import tempfile

    from approximately.exporter import export_store
    from approximately.importer import import_file

    source = TraceStore(tmp_path / "src")
    rec = Recorder("closure", save=False)
    rec.respond("done", success=True)
    source.save(rec.trace)
    out = Path(tempfile.mkdtemp())
    export_store(source, out / "t.json", fmt="otel")
    back = TraceStore(tmp_path / "back")
    import_file(out / "t.json", back)
    again = out / "t2.json"
    export_store(back, again, fmt="otel")
    assert (out / "t.json").read_bytes() == again.read_bytes()
    trace = back.list_traces()[0]
    assert "attr.service.name" not in trace.meta
