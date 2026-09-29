"""v198: MCP `annotate` mirrors `from_anomalies` — triage drafts over
MCP too. Same semantics as the CLI: one draft note per top anomaly,
author `approximately`, verdict left empty, traces with notes never
re-drafted. An MCP agent can now start the triage queue itself.
"""

import json

from approximately.mcp_server import ServerContext, handle_request
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _seed(directory):
    store = TraceStore(directory)
    jitter = (1800, 2000, 2100, 1900)
    for i in range(4):
        rec = Recorder(f"boring {i}", save=False)
        rec.tool("search", {"q": str(i)}, result="hit")
        rec.respond("done", success=True)
        rec.trace.steps[0].latency_ms = jitter[i]
        store.save(rec.trace)
    slow = Recorder("the slow one", save=False)
    slow.tool("search", {"q": "heavy"}, result="hit")
    slow.respond("done", success=True)
    slow.trace.steps[0].latency_ms = 30000
    store.save(slow.trace)
    return store


def _call(arguments, store_dir="."):
    ctx = ServerContext(store_dir)
    return handle_request({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "annotate", "arguments": arguments},
    }, ctx)


def test_mcp_annotate_from_anomalies(tmp_path):
    store = _seed(tmp_path / "s")
    payload = _call({"from_anomalies": True,
                     "store": str(store.directory)})
    result = json.loads(payload["result"]["content"][0]["text"])
    assert result == {"drafted": 1, "fleet_anomalies": 1}
    # re-run: nothing new
    again = _call({"from_anomalies": True,
                   "store": str(store.directory)})
    again_result = json.loads(again["result"]["content"][0]["text"])
    assert again_result["drafted"] == 0
