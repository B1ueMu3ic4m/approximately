"""v218: spool ops — doctor checks it, agents can drive it.

The spool round shipped the watcher; this round gives the two other
surfaces their handle on it: `doctor --spool DIR` reports pending
files and the ones no pass could parse (they stay put by design, so
they count against health), and MCP gains `spool_once` so an agent
can run an ingest pass itself.
"""

import argparse
import json

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


def test_tool_inventory_grew_to_32():
    from approximately.mcp_server import _TOOLS

    assert len(_TOOLS) == 32
    names = {t["name"] for t in _TOOLS}
    assert "spool_once" in names
