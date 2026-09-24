"""v0.48 — MCP trend and stats tools (CLI/MCP capability parity)."""

from __future__ import annotations

import io
import json
import time

from approximately.mcp_server import (
    _TOOLS,
    ServerContext,
    handle_request,
    serve,
)
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _rpc(method, params=None, request_id=1):
    msg = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        msg["params"] = params
    return json.dumps(msg)


def _serve(lines, ctx):
    out = io.StringIO()
    served = serve(iter(lines).__next__, out.write, ctx,
                   max_requests=len(lines))
    return out.getvalue(), served


def _store(tmp_path):
    store = TraceStore(str(tmp_path / "traces"))
    for i, ok in enumerate([True, False, False]):
        rec = Recorder(f"task {i}", save=False)
        rec.trace.id = f"ts-{i}"
        rec.tool("bash", {"cmd": "ls"}, result="ok")
        rec.respond("done" if ok else "gave up", success=ok)
        if not ok:
            rec.trace.meta["detections"] = [{"mode": "FM-3.2"}]
        store.save(rec.trace)
    return store


def _digest_dir(tmp_path):
    digests = tmp_path / "digests"
    digests.mkdir()
    base = time.time() - 86400
    rates = [(6, 2.0 / 6), (6, 4.0 / 6)]
    for day, (traces, rate) in enumerate(rates):
        stamp = time.strftime("%Y%m%d", time.gmtime(base + day * 86400))
        snap = {"ts": base + day * 86400 + 43200, "worsening": [],
                "stores": [{"name": "core", "path": "/x",
                            "traces": traces, "failure_rate": rate,
                            "trend_verdict": "stable",
                            "trend_slope": 0.0, "worsening": False,
                            "top_modes": [{"mode": "FM-2.1",
                                           "count": day + 1}],
                            "top_agents": [{"agent": "worker",
                                            "steps": 3,
                                            "tool_calls": 2,
                                            "errors": day,
                                            "tokens": 30,
                                            "traces": traces,
                                            "failed_traces": day + 1,
                                            "failure_rate": rate}]}]}
        (digests / f"digest-{stamp}.jsonl").write_text(
            json.dumps(snap, sort_keys=True) + "\n", encoding="utf-8")
    return digests


def test_tools_list_has_twelve_tools():
    ctx = ServerContext(".")
    raw, _ = _serve([_rpc("tools/list")], ctx)
    names = [t["name"] for t in
             json.loads(raw.strip().splitlines()[0])["result"]["tools"]]
    assert len(names) == 12 and "trend" in names and "stats" in names
    assert len(_TOOLS) == 12


def test_mcp_trend_returns_day_series(tmp_path):
    digests = _digest_dir(tmp_path)
    msg = json.loads(_rpc("tools/call", {
        "name": "trend", "arguments": {"digest_dir": str(digests)}}))
    resp = handle_request(msg, ServerContext("."))
    payload = json.loads(resp["result"]["content"][0]["text"])
    assert len(payload["days"]) == 2
    assert payload["days"][0]["failure_rate"] == round(2.0 / 6, 4)
    assert payload["days"][1]["top_modes"][0][0] == "FM-2.1"
    assert resp["result"]["isError"] is False


def test_mcp_trend_missing_dir_is_empty_history(tmp_path):
    # a nonexistent digest dir yields an empty history, not an error
    msg = json.loads(_rpc("tools/call", {
        "name": "trend",
        "arguments": {"digest_dir": str(tmp_path / "nope")}}))
    resp = handle_request(msg, ServerContext("."))
    payload = json.loads(resp["result"]["content"][0]["text"])
    assert resp["result"]["isError"] is False
    assert payload["days"] == [] and payload["snapshots"] == 0


def test_mcp_stats_aggregates_selection(tmp_path):
    store = _store(tmp_path)
    msg = json.loads(_rpc("tools/call", {
        "name": "stats",
        "arguments": {"expression": "success == false"},
        }, ) if False else _rpc("tools/call", {
        "name": "stats",
        "arguments": {"expression": "success == false",
                      "store": str(store.directory)}}))
    resp = handle_request(msg, ServerContext(str(store.directory)))
    payload = json.loads(resp["result"]["content"][0]["text"])
    assert payload["count"] == 2
    assert payload["failed"] == 2
    assert payload["failure_rate"] == 1.0
    assert payload["modes"] == {"FM-3.2": 2}


def test_mcp_stats_zero_matches(tmp_path):
    store = _store(tmp_path)
    msg = json.loads(_rpc("tools/call", {
        "name": "stats",
        "arguments": {"expression": "task contains 'zzz-nope'",
                      "store": str(store.directory)}}))
    resp = handle_request(msg, ServerContext(str(store.directory)))
    payload = json.loads(resp["result"]["content"][0]["text"])
    assert payload["count"] == 0


def test_mcp_trend_agent_param(tmp_path):
    """v0.56: trend accepts an agent name — per-day rollup with its
    own Theil-Sen verdict, mirroring fleet --trend --agent."""
    digests = _digest_dir(tmp_path)
    resp = handle_request({
        "jsonrpc": "2.0", "id": 9, "method": "tools/call",
        "params": {"name": "trend",
                   "arguments": {"digest_dir": str(digests),
                                 "agent": "worker"}},
    }, ServerContext("."))
    payload = json.loads(resp["result"]["content"][0]["text"])
    assert payload["agent"] == "worker"
    assert [d["steps"] for d in payload["days"]] == [3, 3]
    assert [d["failed_traces"] for d in payload["days"]] == [1, 2]
    assert payload["verdict"] in ("stable", "improving", "worsening")

    # no agent: fleet-level summary unchanged
    resp = handle_request({
        "jsonrpc": "2.0", "id": 10, "method": "tools/call",
        "params": {"name": "trend",
                   "arguments": {"digest_dir": str(digests)}},
    }, ServerContext("."))
    payload = json.loads(resp["result"]["content"][0]["text"])
    assert "agent" not in payload and "days" in payload
