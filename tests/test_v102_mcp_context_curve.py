"""v102: MCP tools #18 context and #19 curve.

`context` (budgeted-runtime forecast: what survives eviction) and
`curve` (budget-recall sweep) become stdio tools — an MCP client can
ask "what does shrinking this run's window cost?" before it happens.
"""

import json

from approximately.mcp_server import _TOOLS, ServerContext, handle_request
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _store(tmp_path):
    store = TraceStore(str(tmp_path / "s"))
    rec = Recorder("context fixture", save=False)
    rec.trace.id = "x-1"
    for i in range(6):
        rec.tool("probe", {"i": i},
                 result=f"flight JT-{i}: SFO-NRT 06-{10 + i} $8{i}0 "
                        f"seat 1{i}A")
    rec.respond("booked JT-3", success=True)
    store.save(rec.trace)
    return store


def _call(name, arguments):
    return handle_request({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    }, ServerContext("."))


def _payload(resp):
    assert resp["result"]["isError"] is False, resp["result"]
    return json.loads(resp["result"]["content"][0]["text"])


def test_registered():
    names = [t["name"] for t in _TOOLS]
    assert "context" in names and "curve" in names


def test_context_forecast(tmp_path):
    store = _store(tmp_path)
    payload = _payload(_call("context", {"trace": "x-1",
                                         "store": str(store.directory),
                                         "budget": 300}))
    assert payload["trace"] == "x-1"
    assert payload["budget"] == 300
    assert payload["full_context_tokens"] > 0
    assert payload["budgeted_tokens"] <= payload["full_context_tokens"]
    assert 0.0 <= payload["final_recall"] <= 1.0


def test_context_tight_budget_evicts(tmp_path):
    store = _store(tmp_path)
    tight = _payload(_call("context", {"trace": "x-1",
                                       "store": str(store.directory),
                                       "budget": 50}))
    loose = _payload(_call("context", {"trace": "x-1",
                                       "store": str(store.directory),
                                       "budget": 100000}))
    assert tight["evicted_steps"] >= loose["evicted_steps"]
    assert loose["final_recall"] >= tight["final_recall"]


def test_curve_monotone_recall(tmp_path):
    store = _store(tmp_path)
    payload = _payload(_call("curve", {"trace": "x-1",
                                       "store": str(store.directory)}))
    assert payload["trace"] == "x-1"
    points = payload["points"]
    assert len(points) >= 5
    recalls = [p["recall"] for p in points]
    assert recalls == sorted(recalls)
    assert all(0.0 <= r <= 1.0 for r in recalls)
    budgets = [p["budget"] for p in points]
    assert budgets == sorted(budgets)


def test_missing_trace_is_tool_error(tmp_path):
    store = _store(tmp_path)
    for name in ("context", "curve"):
        resp = _call(name, {"trace": "nope",
                            "store": str(store.directory)})
        assert resp["result"]["isError"] is True
