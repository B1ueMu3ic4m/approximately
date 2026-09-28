"""v134: MCP resource surface grows a stats snapshot.

`approximately://{store}/stats.json` joins annotations.jsonl and the
per-trace resources: a client can read store health (trace count,
failure rate, top failure modes) without calling a tool — the browse
path for dashboards and quick checks.
"""

import json

from approximately.mcp_server import ServerContext, handle_request
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _ctx_and_request(method, params):
    return {
        "jsonrpc": "2.0", "id": 1, "method": method,
        "params": params,
    }


def _store_with_failures(directory):
    store = TraceStore(directory)
    for i in range(3):
        rec = Recorder(f"run {i}", save=False)
        if i < 2:
            rec.tool("search", {"q": "x"}, result=None, error="timeout")
            rec.respond("gave up", success=False)
        else:
            rec.respond("done", success=True)
        store.save(rec.trace)
    return store


def test_stats_resource_listed_and_readable(tmp_path):
    store = _store_with_failures(tmp_path / "s")
    ctx = ServerContext(str(store.directory))
    listed = handle_request(_ctx_and_request("resources/list", {}),
                            ctx)
    uris = [r["uri"] for r in listed["result"]["resources"]]
    stats_uri = f"approximately://{store.directory}/stats.json"
    assert stats_uri in uris
    read = handle_request(_ctx_and_request(
        "resources/read", {"uri": stats_uri}), ctx)
    body = read["result"]["contents"][0]
    assert body["mimeType"] == "application/json"
    payload = json.loads(body["text"])
    assert payload["traces"] == 3
    assert payload["failures"] == 2
    assert 0 < payload["failure_rate"] < 1
    assert payload["top_modes"] == {"FM-3.1": 2}


def test_annotations_resource_still_readable(tmp_path):
    store = _store_with_failures(tmp_path / "s")
    store.annotate(store.list_traces()[0].id, "looks environmental",
                   verdict="confirmed")
    ctx = ServerContext(str(store.directory))
    read = handle_request(_ctx_and_request(
        "resources/read",
        {"uri": f"approximately://{store.directory}/annotations.jsonl"}),
        ctx)
    text = read["result"]["contents"][0]["text"]
    assert "looks environmental" in text


def test_unknown_uri_still_param_error():
    ctx = ServerContext(".")
    read = handle_request(_ctx_and_request(
        "resources/read",
        {"uri": "approximately:///nowhere/stats.json"}), ctx)
    assert read["error"]["code"] == -32602
