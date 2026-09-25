"""v107: fuzz round 5 — tonight's surfaces.

Round 5 targets v0.73-v0.75: the query DSL's new tools/errors
fields, the four shared payload constructors (similar / drift /
counterfactual / predict), and the annotations sidecar. Contract
unchanged: documented errors or clean skips, never a crash.
"""

import json
import random

from approximately.mcp_server import ServerContext, handle_request
from approximately.query import parse, select
from approximately.recorder import Recorder
from approximately.store import TraceStore

SEED = 20260925


def _call(name, arguments):
    return handle_request({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    }, ServerContext("."))


def _assert_tool_result(resp):
    assert "result" in resp, resp
    assert resp["result"]["isError"] in (True, False)
    if resp["result"]["isError"] is False:
        json.loads(resp["result"]["content"][0]["text"])


def _weird_trace(rng, tid):
    rec = Recorder(f"f5 {tid}", save=False)
    rec.trace.id = tid
    roll = rng.random()
    if roll < 0.3:
        pass
    else:
        rec.tool(rng.choice(["deploy", "", "\x00", None]),
                 rng.choice([{}, None, {"env": rng.choice([1, None])}]),
                 result=rng.choice([None, "", "ok"]),
                 error=rng.choice([None, "", "boom"]),
                 agent=rng.choice([None, "", "a"]))
        rec.respond(rng.choice(["done", ""]),
                    success=rng.choice([True, False, None]))
    return rec.trace


def test_fuzz_query_new_fields(tmp_path):
    rng = random.Random(SEED)
    store = TraceStore(str(tmp_path / "s"))
    for i in range(8):
        store.save(_weird_trace(rng, f"q-{i}"))
    traces = store.list_traces()
    for expr in [
        "tools contains 'deploy'",
        "tools contains '\x00'",
        "not (tools != tools)",
        "errors >= 1",
        "errors > -1",
        "errors == 0 or errors == 1",
        "tools contains 'deploy' and errors >= 0",
        "mode == FM-2.1 or tools contains 'x' or errors < 9",
    ]:
        predicate = parse(expr)
        for t in traces:
            predicate(t)  # must not raise
        select(traces, expr)


def test_fuzz_payload_constructors(tmp_path):
    rng = random.Random(SEED + 1)
    store = TraceStore(str(tmp_path / "s"))
    for i in range(8):
        store.save(_weird_trace(rng, f"pc-{i}"))
    traces = store.list_traces()

    from approximately.align import similar_payload
    from approximately.counterfactual import counterfactual
    from approximately.counterfactual import report_payload as cf_payload
    from approximately.drift import detect_drift, report_payload
    from approximately.precursor import PrecursorModel, score_payload

    for tid in [f"pc-{i}" for i in range(8)]:
        target = store.load(tid)
        payload = similar_payload(target, traces, top=rng.choice(
            [0, 1, 5, 99, -3]))
        assert isinstance(payload["matches"], list)
        cf = cf_payload(counterfactual(target))
        assert isinstance(cf["interventions"], list)
        model = PrecursorModel()
        for t in traces:
            if t.id != tid:
                model.observe(t)
        sp = score_payload(target, model.probability(target))
        assert 0.0 <= sp["probability"] <= 1.0

    ordered = sorted(traces, key=lambda t: t.created_at or 0)
    half = max(1, len(ordered) // 2)
    dr = report_payload(detect_drift(ordered[:half], ordered[half:]))
    # PSI is unbounded above on skewed histograms; shape only
    assert dr["psi"] >= 0.0
    assert dr["verdict"]


def test_fuzz_annotations_sidecar(tmp_path):
    """Garbage in the sidecar never breaks read or write."""
    rng = random.Random(SEED + 2)
    store = TraceStore(str(tmp_path / "s"))
    store.save(_weird_trace(rng, "an-0"))
    path = store.directory / "annotations.jsonl"
    lines = [
        json.dumps({"trace_id": "an-0", "note": "real"}),
        "",
        "not json",
        '{"trace_id": "an-0"',                # truncated
        "[1, 2, 3]",                          # wrong shape
        '{"trace_id": 5, "note": null}',      # wrong types
        "null",
        '{"ts": "x", "trace_id": "an-0", "note": 42}',
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    rows = store.annotations()
    assert isinstance(rows, list)
    assert all(isinstance(r, dict) for r in rows)
    assert any(r.get("note") == "real" for r in rows)
    # writing still works after garbage
    store.annotate("an-0", "post-garbage")
    assert any(r.get("note") == "post-garbage"
               for r in store.annotations("an-0"))


def test_fuzz_annotate_tool(tmp_path):
    rng = random.Random(SEED + 3)
    store = TraceStore(str(tmp_path / "s"))
    store.save(_weird_trace(rng, "t-0"))
    for note in [None, "", "\x00", "x" * 5000, "ok note"]:
        args = {"trace": "t-0", "store": str(store.directory)}
        if note is not None:
            args["note"] = note
        _assert_tool_result(_call("annotate", args))
    for tid in ["t-0", "missing", "", "\x00"]:
        _assert_tool_result(_call("annotate", {
            "trace": tid, "store": str(store.directory)}))
