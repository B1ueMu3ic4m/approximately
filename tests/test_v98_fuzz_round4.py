"""v98: fuzz round 4 — the surfaces added since round 3.

Round 4 targets v0.60-v0.63: the recidivist filter
(agent_scorecard min_failed, scoreboard.min_failed), the shared
verdict ladder (integrity.verdict_payload via the MCP verify tool,
including keyed/wrong-key/ledger states), and the new MCP cluster
tool. Contract unchanged: documented errors or clean skips, never a
crash that escapes as a protocol fault.
"""

import json
import random

from approximately.cluster import agent_scorecard
from approximately.integrity import sign
from approximately.mcp_server import ServerContext, handle_request
from approximately.recorder import Recorder
from approximately.store import TraceStore

SEED = 20260925

GARBAGE = [
    "", "\x00", "null", "NaN", "Infinity", "-1", "0", "1e999", "{}",
    "[]", "x" * 3000, "\U0001D4CA\u202E", "'", '"', "\\", 0, -1,
    1e308, True, False, None, [], {},
]


def _call(name, arguments):
    ctx = ServerContext(".")
    return handle_request({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    }, ctx)


def _assert_tool_result(resp):
    """Either a clean payload or a tool-level error — never a fault."""
    assert "result" in resp, resp
    assert resp["result"]["isError"] in (True, False)
    if resp["result"]["isError"] is False:
        json.loads(resp["result"]["content"][0]["text"])


def _weird_trace(rng, tid):
    rec = Recorder(f"fuzz {tid}", save=False)
    rec.trace.id = tid
    roll = rng.random()
    if roll < 0.2:
        pass  # zero steps
    elif roll < 0.5:
        rec.tool(rng.choice(["search", "\x00", ""]),
                 rng.choice([{}, {"q": None}, {"q": 1e999}]),
                 result=rng.choice([None, "", "ok"]),
                 error=rng.choice([None, "boom", ""]),
                 agent=rng.choice([None, "", "a", "\x00"]))
        if rng.random() < 0.5:
            rec.respond("done", success=rng.choice([True, False, None]))
    else:
        rec.plan(rng.choice(["think", "", None]))
        rec.respond(rng.choice(["done", ""]), success=rng.choice(
            [True, False, None]))
    if rng.random() < 0.5:
        sign(rec.trace, key=rng.choice([b"k1", b"k2"]))
    return rec.trace


def test_fuzz_scoreboard_min_failed(tmp_path):
    """min_failed garbage must never escape as a protocol fault."""
    rng = random.Random(SEED)
    store = TraceStore(str(tmp_path / "s"))
    for i in range(6):
        store.save(_weird_trace(rng, f"sb-{i}"))
    for value in [*GARBAGE, -5, 0.5, 2.9, "3"]:
        resp = _call("scoreboard", {"store": str(store.directory),
                                    "min_failed": value})
        _assert_tool_result(resp)


def test_fuzz_scorecard_library(tmp_path):
    """The library call itself takes any int-like without crashing —
    and negative thresholds keep every row."""
    rng = random.Random(SEED + 1)
    traces = [_weird_trace(rng, f"lib-{i}") for i in range(5)]
    for value in (-5, 0, 1, 99, True):
        rows = agent_scorecard(traces, min_failed=value)
        assert isinstance(rows, list)
    rows = agent_scorecard(traces, min_failed=-5)
    assert rows == agent_scorecard(traces)


def test_fuzz_verify_ladder(tmp_path):
    """Verify over garbage integrity blocks, wrong keys, hostile
    key_file paths — the full ladder, no crashes."""
    rng = random.Random(SEED + 2)
    store = TraceStore(str(tmp_path / "s"))
    for i in range(6):
        store.save(_weird_trace(rng, f"vf-{i}"))
    # corrupt the integrity blocks on disk in every direction
    for path in sorted(store.directory.glob("vf-*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        meta = data.setdefault("meta", {})
        roll = rng.random()
        if roll < 0.25:
            meta.pop("integrity", None)
        elif roll < 0.5:
            meta["integrity"] = rng.choice([
                {}, {"algorithm": "??"}, {"algorithm": "hmac-sha256"},
                {"algorithm": "hmac-sha256", "step_hashes": "x"},
                {"algorithm": "hmac-sha256", "step_hashes": [],
                 "final": None, "key_id": 7},
            ])
        elif roll < 0.75:
            data["steps"] = rng.choice([[], None,
                                        [{"kind": "tool_call"}]])
        path.write_text(json.dumps(data), encoding="utf-8")
    key_file = tmp_path / "k"
    key_file.write_bytes(b"k1")
    for tid in [f"vf-{i}" for i in range(6)] + ["missing"]:
        for kf in (None, str(key_file), str(tmp_path / "nope")):
            args = {"trace": tid, "store": str(store.directory)}
            if kf:
                args["key_file"] = kf
            _assert_tool_result(_call("verify", args))


def test_fuzz_cluster_tool(tmp_path):
    """Cluster tool with garbage thresholds, by_agent and top."""
    rng = random.Random(SEED + 3)
    store = TraceStore(str(tmp_path / "s"))
    for i in range(6):
        store.save(_weird_trace(rng, f"cl-{i}"))
    for min_size in [*GARBAGE, 2.5, -1]:
        _assert_tool_result(_call("cluster", {
            "store": str(store.directory), "min_size": min_size}))
    for by_agent in GARBAGE:
        _assert_tool_result(_call("cluster", {
            "store": str(store.directory), "by_agent": by_agent}))
    for top in [*GARBAGE, 0, -2, 1.5]:
        _assert_tool_result(_call("cluster", {
            "store": str(store.directory), "top": top}))


def test_load_key_refuses_huge_file(tmp_path):
    """Fuzz round 4 find: key_file had no size bound — a hostile
    pointer at a giant (or unbounded-device-backed) regular file
    would be read whole into memory. Keys are tiny; refuse big."""
    import pytest

    from approximately.integrity import load_key

    big = tmp_path / "big.key"
    big.write_bytes(b"k" * 10_000)
    with pytest.raises(ValueError, match="not a key"):
        load_key(str(big))

    good = tmp_path / "good.key"
    good.write_bytes(b"exact-key\n")
    assert load_key(str(good)) == b"exact-key"


def test_mcp_verify_huge_key_file_is_tool_error(tmp_path):
    from approximately.recorder import Recorder as R
    from approximately.store import TraceStore as TS

    store = TS(str(tmp_path / "s"))
    rec = R("t", save=False)
    rec.trace.id = "t1"
    rec.respond("done", success=True)
    sign(rec.trace, key=b"k")
    store.save(rec.trace)

    big = tmp_path / "big.key"
    big.write_bytes(b"k" * 10_000)
    resp = _call("verify", {"trace": "t1",
                            "store": str(store.directory),
                            "key_file": str(big)})
    assert resp["result"]["isError"] is True
