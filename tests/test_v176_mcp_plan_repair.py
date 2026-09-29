"""v176: MCP tool #31 — `plan_repair` mirrors the planning half.

`repair` writes nothing unless `--apply`; the planning half is
read-only analysis and therefore mirrors into MCP per the ops-pair
rule: an agent stack asks "what's the smallest honest intervention
set for this trace" and gets applied/cleared/remaining/unrepairable
as data. The write half (`--apply`, a `.repaired.json` file) stays
deliberately CLI-only.
"""

import json

from approximately.mcp_server import _TOOLS, ServerContext, handle_request
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _seed(directory):
    store = TraceStore(directory)
    rec = Recorder("repeat and derail", save=False)
    for _ in range(3):
        rec.tool("search", {"q": "same"}, result="same hits")
    rec.respond("still stuck", success=False)
    store.save(rec.trace)
    return store


def _call(arguments, store_dir="."):
    ctx = ServerContext(store_dir)
    return handle_request({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "plan_repair", "arguments": arguments},
    }, ctx)


def test_plan_repair_payload(tmp_path):
    store = _seed(tmp_path / "s")
    trace = store.list_traces()[0]
    payload = _call({"trace": trace.id,
                     "store": str(store.directory)})
    result = json.loads(payload["result"]["content"][0]["text"])
    assert result["trace"] == trace.id
    assert isinstance(result["applied"], list)
    assert isinstance(result["cleared_modes"], list)
    assert isinstance(result["remaining_modes"], list)
    assert isinstance(result["unrepairable"], list)
    assert result["repaired"] == bool(result["cleared_modes"])
    assert "summary" in result


def test_plan_repair_missing_trace_is_tool_error(tmp_path):
    payload = _call({"trace": "ghost123"}, ".")
    assert payload["result"]["isError"] is True
    assert "no trace" in json.dumps(payload["result"]["content"])


def test_listed_with_required_trace():
    schema = next(t for t in _TOOLS if t["name"] == "plan_repair")
    assert schema["inputSchema"]["required"] == ["trace"]
