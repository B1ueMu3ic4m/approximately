"""v86: MCP tool #11 — bench_gate, closing the CLI-parity gap.

The gate existed as a command (#142) and as a reusable action, but
MCP clients could not run it. The tool returns the structured
gate_result (records, per-mode P/R/F1, sample macro-F1, violations,
passed) instead of an exit code; bad inputs surface as tool errors.
"""

import json

from approximately.mcp_server import _TOOLS, ServerContext, handle_request


def _call(arguments, request_id=1):
    ctx = ServerContext(".")
    return handle_request({
        "jsonrpc": "2.0", "id": request_id, "method": "tools/call",
        "params": {"name": "bench_gate", "arguments": arguments},
    }, ctx)


def test_bench_gate_registered():
    assert "bench_gate" in [t["name"] for t in _TOOLS]


def test_bench_gate_passes_fixture(tmp_path):
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    resp = _call({
        "dataset": str(root / "examples" / "action" / "fixture.jsonl"),
        "floors": str(root / "examples" / "action" / "floors.json"),
    })
    assert resp["result"]["isError"] is False
    payload = json.loads(resp["result"]["content"][0]["text"])
    assert payload["passed"] is True
    assert payload["records"] == 8
    assert payload["sample_f1"] == 1.0
    assert payload["violations"] == []
    for mode in ("FM-1.3", "FM-2.1", "FM-2.6", "FM-3.2"):
        assert payload["modes"][mode]["precision"] == 1.0


def test_bench_gate_reports_violations_not_exit(tmp_path):
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    resp = _call({
        "dataset": str(root / "examples" / "action" / "fixture.jsonl"),
        "floors": str(root / "examples" / "action"
                      / "floors-impossible.json"),
    })
    payload = json.loads(resp["result"]["content"][0]["text"])
    # MCP reports gate failures as data, not transport errors:
    # the tool ran fine, the gate is red.
    assert resp["result"]["isError"] is False
    assert payload["passed"] is False
    assert any("no score (required)" in v for v in payload["violations"])


def test_bench_gate_bad_inputs_are_tool_errors():
    resp = _call({"dataset": "/nope/x.jsonl", "floors": "/nope/f.json"})
    assert resp["result"]["isError"] is True
    resp = _call({"dataset": ""})
    assert resp["result"]["isError"] is True
