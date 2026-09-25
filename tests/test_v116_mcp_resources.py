"""v116: MCP resources — browse a store without calling tools.

`resources/list` exposes one resource per trace plus the annotation
sidecar; `resources/read` returns a trace's JSON or the annotations
NDJSON. The initialize handshake now advertises the resources
capability. Unsupported URI schemes and unknown traces are -32602
parameter errors, not crashes.
"""

import json

from approximately.mcp_server import ServerContext, handle_request
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _store(tmp_path):
    store = TraceStore(str(tmp_path / "s"))
    rec = Recorder("resource fixture", save=False)
    rec.trace.id = "r-1"
    rec.respond("done", success=False)
    store.save(rec.trace)
    store.annotate("r-1", "infra timeout", verdict="confirmed")
    return store


def _request(method, params=None, store=None):
    return handle_request({
        "jsonrpc": "2.0", "id": 1, "method": method,
        "params": params or {},
    }, ServerContext(store or "."))


def test_initialize_advertises_resources(tmp_path):
    store = _store(tmp_path)
    resp = _request("initialize", store=str(store.directory))
    caps = resp["result"]["capabilities"]
    assert "resources" in caps


def test_resources_list(tmp_path):
    store = _store(tmp_path)
    resp = _request("resources/list", store=str(store.directory))
    resources = resp["result"]["resources"]
    uris = [r["uri"] for r in resources]
    assert any(u.endswith("/annotations.jsonl") for u in uris)
    assert any(u.endswith("/traces/r-1") for u in uris)
    trace_res = [r for r in resources if r["uri"].endswith("/traces/r-1")]
    assert "failed" in trace_res[0]["description"]


def test_resources_read_trace(tmp_path):
    store = _store(tmp_path)
    uri = f"approximately://{store.directory}/traces/r-1"
    resp = _request("resources/read", {"uri": uri},
                    store=str(store.directory))
    contents = resp["result"]["contents"][0]
    assert contents["uri"] == uri
    payload = json.loads(contents["text"])
    assert payload["id"] == "r-1"


def test_resources_read_annotations(tmp_path):
    store = _store(tmp_path)
    uri = f"approximately://{store.directory}/annotations.jsonl"
    resp = _request("resources/read", {"uri": uri},
                    store=str(store.directory))
    text = resp["result"]["contents"][0]["text"]
    assert "infra timeout" in text
    assert "confirmed" in text


def test_resources_read_unknown_trace_is_param_error(tmp_path):
    store = _store(tmp_path)
    uri = f"approximately://{store.directory}/traces/nope"
    resp = _request("resources/read", {"uri": uri},
                    store=str(store.directory))
    assert resp["error"]["code"] == -32602


def test_resources_read_bad_scheme_is_param_error(tmp_path):
    resp = _request("resources/read", {"uri": "file:///etc/passwd"},
                    store=str(_store(tmp_path).directory))
    assert resp["error"]["code"] == -32602
