"""v101: MCP tools #16 counterfactual and #17 predict.

`counterfactual` (leave-one-out root cause) and `predict` (failure
precursor probability mined from the store) become stdio tools — the
deep-analysis surface is now fully reachable from an MCP client.
"""

import json

from approximately.mcp_server import _TOOLS, ServerContext, handle_request
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _store(tmp_path):
    """Three failed runs that repeat the same bad tool call, two clean
    ones — enough for counterfactual structure and precursor mining."""
    store = TraceStore(str(tmp_path / "s"))
    for i in range(5):
        rec = Recorder(f"task {i}", save=False)
        rec.trace.id = f"c-{i}"
        ok = i >= 3
        rec.tool("search", {"q": i}, result=None if not ok else "hit",
                 error=None if ok else "timeout")
        rec.tool("deploy", {"env": "prod"}, result="deployed")
        rec.respond("done", success=ok)
        store.save(rec.trace)
    return store


def _call(arguments):
    return handle_request({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "counterfactual", "arguments": arguments},
    }, ServerContext("."))


def _predict_call(arguments):
    return handle_request({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "predict", "arguments": arguments},
    }, ServerContext("."))


def _payload(resp):
    assert resp["result"]["isError"] is False, resp["result"]
    return json.loads(resp["result"]["content"][0]["text"])


def test_registered():
    names = [t["name"] for t in _TOOLS]
    assert "counterfactual" in names and "predict" in names


def test_counterfactual_shape(tmp_path):
    store = _store(tmp_path)
    payload = _payload(_call({"trace": "c-0",
                              "store": str(store.directory)}))
    assert payload["trace"] == "c-0"
    assert payload["baseline_primary"]
    assert isinstance(payload["interventions"], list)
    for iv in payload["interventions"]:
        assert {"removed_step", "mode_id", "eliminated",
                "was_primary"} <= set(iv)
    assert isinstance(payload["causal_ranking"], list)


def test_counterfactual_missing_trace_is_tool_error(tmp_path):
    store = _store(tmp_path)
    resp = _call({"trace": "nope", "store": str(store.directory)})
    assert resp["result"]["isError"] is True


def test_predict_shape_and_range(tmp_path):
    store = _store(tmp_path)
    payload = _payload(_predict_call({"trace": "c-0",
                                      "store": str(store.directory)}))
    assert payload["trace"] == "c-0"
    assert 0.0 <= payload["probability"] <= 1.0
    assert payload["verdict"] in ("HIGH RISK", "elevated", "normal")
    assert payload["mined_traces"] == 4  # every other trace
    assert isinstance(payload["contributors"], list)


def test_predict_missing_trace_is_tool_error(tmp_path):
    store = _store(tmp_path)
    resp = _predict_call({"trace": "nope",
                          "store": str(store.directory)})
    assert resp["result"]["isError"] is True
