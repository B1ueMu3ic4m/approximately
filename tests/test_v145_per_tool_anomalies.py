"""v145: per-tool latency baselines — stop pooling apples and cranes.

A trace that mixes 2-second searches with 30-second deploys pools
every step into one median/MAD scale where *neither* looks anomalous:
the searches sit far below the median (invisible: fast is "fine") and
a 3x deploy slowdown hides inside the spread the searches create.
`detect_latency_anomalies(per_tool=True)` baselines each tool family
separately; families smaller than min_samples fall back to the pooled
scale instead of going blind on rare tools.
"""

import argparse
import json

from approximately.anomaly import detect_latency_anomalies
from approximately.cli import cmd_anomalies
from approximately.mcp_server import ServerContext, handle_request
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _mixed_trace(directory):
    store = TraceStore(directory)
    rec = Recorder("mixed speeds", save=False)
    # five search calls: tight and fast
    for i in range(5):
        rec.tool("search", {"q": str(i)}, result="hit")
    # then five deploy calls, the last tripling its family's norm
    for _ in range(5):
        rec.tool("deploy", {"env": "prod"}, result="ok")
    rec.respond("done", success=True)
    latencies = [1800, 2100, 1900, 2200, 2000,       # searches
                 28000, 30000, 29000, 31000, 90000]  # deploys
    for step, ms in zip(rec.trace.steps, latencies, strict=False):
        step.latency_ms = ms
    store.save(rec.trace)
    return rec.trace, store


def test_pooled_scale_masks_the_deploy_spike(tmp_path):
    trace, _ = _mixed_trace(tmp_path / "s")
    pooled = detect_latency_anomalies(trace, threshold=3.5)
    assert all(a.tool != "deploy" or abs(a.robust_z) < 6
               for a in pooled) or pooled == []


def test_per_tool_baselines_catch_it(tmp_path):
    trace, _ = _mixed_trace(tmp_path / "s")
    per_tool = detect_latency_anomalies(trace, threshold=3.5,
                                        per_tool=True)
    deploy_hits = [a for a in per_tool if a.tool == "deploy"]
    assert deploy_hits, "the 90s deploy must stand out in its family"
    top = per_tool[0]
    assert top.tool == "deploy" and top.latency_ms == 90000
    assert top.median_ms < 32000  # baseline is the deploy family's
    search_hits = [a for a in per_tool if a.tool == "search"]
    assert search_hits == []


def test_rare_tools_fall_back_to_pooled_scale(tmp_path):
    store = TraceStore(tmp_path / "s")
    rec = Recorder("rare tool", save=False)
    for i in range(6):
        rec.tool("search", {"q": str(i)}, result="hit")
    rec.tool("exotic", {"x": 1}, result="ok")
    rec.respond("done", success=True)
    for step, ms in zip(rec.trace.steps,
                        [100, 110, 100, 120, 100, 110, 5000], strict=False):
        step.latency_ms = ms
    store.save(rec.trace)
    per_tool = detect_latency_anomalies(rec.trace, per_tool=True)
    assert [a.tool for a in per_tool] == ["exotic"]


def test_cli_anomalies_per_tool(tmp_path, capsys):
    trace, store = _mixed_trace(tmp_path / "s")
    args = argparse.Namespace(store=str(store.directory),
                              trace=trace.id, threshold=3.5,
                              per_tool=True, json=True)
    rc = cmd_anomalies(args)
    payload = json.loads(capsys.readouterr().out)
    assert any(a["tool"] == "deploy" for a in payload)
    assert rc == 1


def test_mcp_anomalies_per_tool(tmp_path):
    trace, store = _mixed_trace(tmp_path / "s")
    ctx = ServerContext(str(store.directory))
    payload = handle_request({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "anomalies",
                   "arguments": {"trace": trace.id, "per_tool": True}},
    }, ctx)
    result = json.loads(payload["result"]["content"][0]["text"])
    assert result["per_tool"] is True
    assert any(a["tool"] == "deploy" for a in result["anomalies"])
