"""v117: fuzz round 6 — the MCP resources surface and its friends.

Round 6 targets v0.79-v0.86: scoreboard.group_by, the resources
list/read surface, the watch alert threshold, merge's sidecar carry,
and the payload constructors' edges. Contract unchanged: documented
errors or clean skips, never a crash.
"""

import json
import random

from approximately.fleet import _should_alert
from approximately.mcp_server import ServerContext, handle_request
from approximately.merge import merge_store
from approximately.recorder import Recorder
from approximately.store import TraceStore

SEED = 20260925


def _call(name, arguments):
    return handle_request({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    }, ServerContext("."))


def _request(method, params, store=None):
    return handle_request({
        "jsonrpc": "2.0", "id": 1, "method": method,
        "params": params,
    }, ServerContext(store or "."))


def _assert_tool_result(resp):
    assert "result" in resp, resp
    assert resp["result"]["isError"] in (True, False)
    if resp["result"]["isError"] is False:
        json.loads(resp["result"]["content"][0]["text"])


def _weird_trace(rng, tid):
    rec = Recorder(f"f6 {tid}", save=False)
    rec.trace.id = tid
    if rng.random() >= 0.3:
        rec.tool(rng.choice(["deploy", "", None]),
                 rng.choice([{}, None]),
                 result=rng.choice([None, "", "ok"]),
                 error=rng.choice([None, "boom"]),
                 agent=rng.choice([None, "", "a"]))
        rec.respond(rng.choice(["done", ""]),
                    success=rng.choice([True, False, None]))
    return rec.trace


def test_fuzz_scoreboard_group_by(tmp_path):
    rng = random.Random(SEED)
    store = TraceStore(str(tmp_path / "s"))
    for i in range(6):
        store.save(_weird_trace(rng, f"g-{i}"))
    for group_by in [None, "", "agent", "tool", "TOOL", "\x00", 1, None,
                     ["tool"]]:
        args = {"store": str(store.directory)}
        if group_by is not None:
            args["group_by"] = group_by
        _assert_tool_result(_call("scoreboard", args))


def test_fuzz_resources(tmp_path):
    rng = random.Random(SEED + 1)
    store = TraceStore(str(tmp_path / "s"))
    for i in range(4):
        store.save(_weird_trace(rng, f"r-{i}"))
    for uri in [
        f"approximately://{store.directory}/traces/r-0",
        f"approximately://{store.directory}/traces/nope",
        f"approximately://{store.directory}/traces/",
        f"approximately://{store.directory}/annotations.jsonl",
        "approximately://", "file:///etc/passwd", "", "\x00",
        "approximately:///tmp/elsewhere/traces/x",
    ]:
        resp = _request("resources/read", {"uri": uri},
                        store=str(store.directory))
        assert "result" in resp or resp.get("error", {}).get("code") in (
            -32602,), resp
    listing = _request("resources/list", {},
                       store=str(store.directory))
    assert "result" in listing


def test_fuzz_alert_threshold(tmp_path):
    rng = random.Random(SEED + 2)

    class FakeSummary:
        def __init__(self):
            self.worsening = rng.choice([True, False])
            self.failure_rate = rng.choice([0.0, 0.2, 0.5, 1.0, -0.1])

    summaries = [FakeSummary() for _ in range(5)]
    for threshold in [None, 0.0, 0.3, 1.0, -1.0, 2.0]:
        result = _should_alert(summaries, threshold)
        assert result in (True, False)


def test_fuzz_merge_sidecar(tmp_path):
    rng = random.Random(SEED + 3)
    source = TraceStore(str(tmp_path / "src"))
    target = TraceStore(str(tmp_path / "dst"))
    for i in range(3):
        source.save(_weird_trace(rng, f"m-{i}"))
        target.save(_weird_trace(rng, f"t-{i}"))
    lines = [
        json.dumps({"trace_id": "m-0", "note": "good"}),
        "garbage line",
        "[1]",
        "null",
    ]
    (source.directory / "annotations.jsonl").write_text(
        "\n".join(lines) + "\n", encoding="utf-8")
    for conflict in ["skip", "replace", "rename"]:
        report = merge_store(source.directory, target,
                             on_conflict=conflict)
        assert isinstance(report.annotations_carried, int)
    # target sidecar stayed readable
    assert isinstance(target.annotations(), list)
