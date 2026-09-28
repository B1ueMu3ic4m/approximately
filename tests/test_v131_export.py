"""v131: `export` + MCP tool #26 — the path out of the store.

`import` (v1.19/v1.20) got foreign logs in; `export` sends traces out
in the dialect other pipelines speak. The OpenAI chat shape preserves
tool errors as `is_error`, so an export/import roundtrip keeps the
failure story; `native` is a lossless, chain-verifying roundtrip.
"""

import argparse
import json

from approximately.cli import cmd_export
from approximately.exporter import export_store, trace_to_messages
from approximately.importer import import_file
from approximately.mcp_server import ServerContext, handle_request
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _store_with_failure(directory):
    store = TraceStore(directory)
    rec = Recorder("list the files", save=False)
    rec.tool("ls", {"path": "/tmp"}, result=None, error="boom")
    rec.respond("gave up", success=False)
    store.save(rec.trace)
    ok = Recorder("say hi", save=False)
    ok.respond("hi", success=True)
    store.save(ok.trace)
    return store


def test_openai_export_roundtrip_preserves_failure(tmp_path):
    store = _store_with_failure(tmp_path / "s")
    out = tmp_path / "out.jsonl"
    result = export_store(store, out)
    assert result["written"] == 2
    fresh = TraceStore(tmp_path / "s2")
    back = import_file(out, fresh)
    assert back["imported"] == 2
    failed = [t for t in fresh.list_traces() if t.success is False]
    assert len(failed) == 1
    assert failed[0].task == "list the files"
    obs = next(s for s in failed[0].steps if s.kind == "observation")
    assert obs.error and obs.tool == "ls"
    tool_call = next(s for s in failed[0].steps if s.kind == "tool_call")
    assert tool_call.tool == "ls"
    assert tool_call.args == {"path": "/tmp"}


def test_export_import_roundtrip_restores_ids(tmp_path):
    store = _store_with_failure(tmp_path / "s")
    out = tmp_path / "out.jsonl"
    export_store(store, out)
    fresh = TraceStore(tmp_path / "s2")
    back = import_file(out, fresh)
    original_ids = {t.id for t in store.list_traces()}
    assert back["trace_ids"] and original_ids
    assert set(back["trace_ids"]) == original_ids
    again = import_file(out, fresh)
    assert again["imported"] == 0 and again["skipped"] == 2


def test_consecutive_tool_calls_merge_into_one_assistant(tmp_path):
    store = TraceStore(tmp_path / "s")
    rec = Recorder("two calls", save=False)
    rec.tool("ls", {"path": "/"}, result="a")
    rec.tool("cat", {"f": "x"}, result="b")
    store.save(rec.trace)
    messages = trace_to_messages(store.load(rec.trace.id))
    assistants = [m for m in messages if m.get("tool_calls")]
    assert len(assistants) == 1
    assert [c["function"]["name"]
            for c in assistants[0]["tool_calls"]] == ["ls", "cat"]
    tool_msgs = [m for m in messages if m.get("role") == "tool"]
    assert [m["tool_call_id"] for m in tool_msgs] == ["call_0", "call_1"]
    assert [m["content"] for m in tool_msgs] == ["a", "b"]


def test_native_export_roundtrip_verifies(tmp_path):
    from approximately.integrity import verify

    store = _store_with_failure(tmp_path / "s")
    out = tmp_path / "native.jsonl"
    export_store(store, out, fmt="native")
    fresh = TraceStore(tmp_path / "s2")
    back = import_file(out, fresh)
    assert back["imported"] == 2
    for trace in fresh.list_traces():
        assert verify(trace).verdict in ("intact", "unsigned")


def test_query_filter_exports_subset(tmp_path):
    store = _store_with_failure(tmp_path / "s")
    out = tmp_path / "failed.jsonl"
    result = export_store(store, out, query_text="success == false")
    assert result["traces"] == 1 and result["written"] == 1
    rows = [json.loads(line) for line in
            out.read_text().strip().splitlines()]
    assert rows[0]["metadata"]["success"] is False


def test_cli_export_json(tmp_path, capsys):
    store = _store_with_failure(tmp_path / "s")
    args = argparse.Namespace(store=str(store.directory),
                              output=str(tmp_path / "out.jsonl"),
                              format="openai-jsonl", query=None,
                              json=True)
    assert cmd_export(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["written"] == 2


def _call(arguments, store_dir):
    ctx = ServerContext(store_dir)
    return handle_request({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "export_transcripts",
                   "arguments": arguments},
    }, ctx)


def test_mcp_export_transcripts(tmp_path):
    store = _store_with_failure(tmp_path / "s")
    out = tmp_path / "out.jsonl"
    payload = _call({"output": str(out), "store": str(store.directory),
                     "query": "success == false"}, str(store.directory))
    result = json.loads(payload["result"]["content"][0]["text"])
    assert result["written"] == 1
    assert out.is_file()
    bad = _call({"output": str(tmp_path / "no" / "x.jsonl")},
                str(store.directory))
    assert bad["result"]["isError"] is True
