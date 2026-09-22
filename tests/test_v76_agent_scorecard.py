"""v76: per-agent identity — Step.agent, Recorder(agent=...), and the
agent scorecard (stats --by-agent).

The serialization contract is the load-bearing part: unset agent must
be OMITTED from to_dict, because the integrity chain hashes that dict
and pre-agent stores must keep verifying. A test, not a comment.
"""

import json

from approximately.cli import build_parser
from approximately.cluster import UNATTRIBUTED, agent_scorecard
from approximately.integrity import compute_chain
from approximately.recorder import Recorder
from approximately.store import TraceStore
from approximately.trace import Step, Trace


def test_unset_agent_omitted_from_dict():
    assert "agent" not in Step(kind="tool_call").to_dict()


def test_set_agent_roundtrips():
    data = Step(kind="tool_call", tool="x", agent="planner").to_dict()
    assert data["agent"] == "planner"
    assert Step.from_dict(data).agent == "planner"


def test_legacy_step_dict_still_loads():
    legacy = {"kind": "tool_call", "tool": "x", "args": {}, "index": 0}
    step = Step.from_dict(legacy)
    assert step.agent is None


def test_agent_field_is_chain_covered():
    steps = [Step(kind="plan", thought="start"),
             Step(kind="tool_call", tool="x", args={"i": 1}),
             Step(kind="response", result="done")]
    # same seed inputs (task/model/created_at), so only step payloads differ
    trace_a = Trace(task="t", id="ca", created_at=1.0,
                    steps=[Step.from_dict(s.to_dict()) for s in steps])
    trace_b = Trace(task="t", id="cb", created_at=1.0,
                    steps=[Step.from_dict(s.to_dict()) for s in steps])
    trace_b.steps[1].agent = "planner"
    chain_a = compute_chain(trace_a)
    chain_b = compute_chain(trace_b)
    assert chain_a[0] == chain_b[0]      # step 0 untouched
    assert chain_a[1] != chain_b[1]      # agent identity is hashed
    assert chain_a[2] != chain_b[2]      # and the chain propagates


def test_recorder_stamps_agent():
    rec = Recorder("t", agent="planner", save=False)
    rec.plan("think")
    rec.tool("bash", {"cmd": "ls"}, result="ok")
    rec.respond("done")
    rec.message("planner", "critic", "review please")
    agents = [s.agent for s in rec.trace.steps]
    assert agents == ["planner", "planner", "planner", "planner"]
    assert rec.trace.steps[3].tool == "planner->critic"


def test_recorder_without_agent_stays_none():
    rec = Recorder("t", save=False)
    rec.tool("bash", {"cmd": "ls"}, result="ok")
    assert rec.trace.steps[0].agent is None


def _two_agent_store(tmp_path):
    store = TraceStore(str(tmp_path / "s"))
    ok = Recorder("good task", save=False, agent="worker")
    ok.tool("bash", {"cmd": "ls"}, result="ok")
    ok.respond("fine")
    bad = Recorder("bad task", save=False, agent="worker")
    bad.tool("bash", {"cmd": "rm -rf /"}, error="boom")
    bad.respond("gave up", success=False)
    free = Recorder("solo task", save=False)
    free.respond("ok")
    for t in (ok.trace, bad.trace, free.trace):
        store.save(t)
    return store


def test_scorecard_math(tmp_path):
    store = _two_agent_store(tmp_path)
    rows = agent_scorecard(store.list_traces())
    by = {r["agent"]: r for r in rows}
    worker = by["worker"]
    assert worker["traces"] == 2 and worker["steps"] == 4
    assert worker["tool_calls"] == 2 and worker["errors"] == 1
    assert worker["failed_traces"] == 1
    assert worker["failure_rate"] == 0.5
    assert by[UNATTRIBUTED]["traces"] == 1
    assert by[UNATTRIBUTED]["failure_rate"] == 0.0


def test_cli_stats_by_agent(tmp_path, capsys):
    store = _two_agent_store(tmp_path)
    parser = build_parser()
    args = parser.parse_args(["stats", "--store", str(store.directory),
                              "--by-agent"])
    assert args.func(args) == 0
    table = capsys.readouterr().out
    assert "worker" in table and UNATTRIBUTED in table
    assert "50%" in table

    args = parser.parse_args(["stats", "--store", str(store.directory),
                              "--by-agent", "--json"])
    assert args.func(args) == 0
    rows = json.loads(capsys.readouterr().out)
    assert {r["agent"] for r in rows} == {"worker", UNATTRIBUTED}
