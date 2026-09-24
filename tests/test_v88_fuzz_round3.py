"""v88: fuzz round 3 — the newest untrusted-input boundaries.

Round 3 targets the surfaces added since v44/v77: digest snapshot
files (agent_trend_days / trend_days), bench-gate floors JSON, the
query DSL's agents field, and the MCP bench_gate tool. Contracts
under test: documented errors or silence, never crashes; gates
refuse to run on corrupt floors; hostile agent names stay contained.
"""

import json
import random
from pathlib import Path

from approximately.benchgate import gate_result
from approximately.fleet import agent_trend_days, trend_days
from approximately.mcp_server import ServerContext, handle_request

SEED = 20260924

GARBAGE_STRINGS = [
    "", "\x00", "\n\n\n", "{}", "[]", "null", "NaN", "Infinity",
    "<script>", "```", "\U0001D4CA\u202E", "x" * 5000, "-1", "1e999",
    "agent" * 200, "'", '"', "\\", "\t\r\n",
]


def _garbage_store(rng):
    """One stores[] entry from the garbage bag."""
    roll = rng.random()
    if roll < 0.3:
        return rng.choice([{}, "x", None])
    agents = rng.choice([
        None, {}, "x",
        [{"agent": rng.choice(GARBAGE_STRINGS),
          "steps": rng.choice([1, -3, "x", None, 1e308])}],
        [{"agent": 5}],
    ])
    return {"name": rng.choice(GARBAGE_STRINGS), "top_agents": agents}


def _write_garbage_digests(tmp_path, rng):
    digests = tmp_path / "digests"
    digests.mkdir()
    for i in range(20):
        lines = []
        for _ in range(rng.randint(0, 4)):
            roll = rng.random()
            if roll < 0.3:
                lines.append("".join(rng.choice("{[,:]0123456789abcdef}")
                                     for _ in range(rng.randint(0, 60))))
            elif roll < 0.6:
                snap = {
                    "ts": rng.choice([0, -5, 1e18, "x", None]),
                    "stores": rng.choice([None, [], {}, "x", _garbage_store(rng)]),
                }
                lines.append(json.dumps(snap, default=str))
            else:
                lines.append(rng.choice(GARBAGE_STRINGS))
        (digests / f"digest-{20260900 + i:08d}.jsonl").write_text(
            "\n".join(lines) + "\n", encoding="utf-8")
    return digests


def test_fuzz_digest_parsers_never_crash(tmp_path):
    rng = random.Random(SEED)
    digests = _write_garbage_digests(tmp_path, rng)
    # both readers return rows built from safe defaults; nothing raises
    day_rows = trend_days(digests)
    agent_rows = agent_trend_days(digests, rng.choice(GARBAGE_STRINGS))
    assert isinstance(day_rows, list) and isinstance(agent_rows, list)
    for row in agent_rows:
        for key in ("steps", "tool_calls", "errors", "traces",
                    "failed_traces"):
            assert isinstance(row[key], int) and row[key] >= 0


def test_fuzz_floors_refused_or_clean(tmp_path):
    rng = random.Random(SEED + 1)
    from approximately.distill import load_dataset

    fixture = (Path(__file__).resolve().parent.parent
               / "examples" / "action" / "fixture.jsonl")
    labeled = load_dataset(fixture, fmt="jsonl")
    assert labeled  # the fixture itself must stay loadable
    for i in range(15):
        floors = tmp_path / f"floors-{i}.json"
        floors.write_text(json.dumps({
            "sample_f1": rng.choice([0.5, -1e400 if False else None,
                                     "x", [], 0.9]),
            "modes": {rng.choice(GARBAGE_STRINGS): {
                "precision": rng.choice([0.5, None, "x", [], {}]),
                "recall": rng.choice([0.5, None]),
                "required": rng.choice([True, False, "yes"]),
            }},
        }, default=str), encoding="utf-8")
        # contract: a verdict dict with a bool passed, never a crash
        try:
            result = gate_result(fixture, floors)
        except ValueError:
            continue  # documented refusal paths (non-finite etc.)
        assert isinstance(result["passed"], bool)
        assert isinstance(result["violations"], list)


def test_fuzz_dsl_agents_field_is_contained(tmp_path):
    from approximately.query import QueryError, select

    rng = random.Random(SEED + 2)
    from approximately.recorder import Recorder

    rec = Recorder("t", save=False)
    rec.tool("bash", {"cmd": "x"}, result="y",
             agent=rng.choice(GARBAGE_STRINGS))
    for _ in range(30):
        expr = rng.choice([
            f"agents contains '{rng.choice(GARBAGE_STRINGS)[:40]}'",
            "agents == set()", "agents contains 'x' and success == false",
            "agents startswith ''", "not agents", "agents > 3",
        ])
        try:
            select([rec.trace], expr)
        except QueryError:
            pass  # documented parse error path


def test_fuzz_mcp_bench_gate_answers_or_errors(tmp_path):
    rng = random.Random(SEED + 3)
    ctx = ServerContext(".")
    for i in range(12):
        payload = {}
        if rng.random() < 0.8:
            payload["dataset"] = str(
                tmp_path / f"d{rng.randint(0, 3)}.jsonl")
        if rng.random() < 0.8:
            payload["floors"] = rng.choice(GARBAGE_STRINGS)
        resp = handle_request({
            "jsonrpc": "2.0", "id": i, "method": "tools/call",
            "params": {"name": "bench_gate", "arguments": payload},
        }, ctx)
        assert resp["result"]["isError"] is True  # unreadable = error
        body = json.loads(resp["result"]["content"][0]["text"])
        assert "error" in body
