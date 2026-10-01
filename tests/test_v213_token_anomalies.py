"""v213: token anomalies — the burn a retry loop leaves behind.

Latency catches the call that ran long; tokens catch the call that
*worked too hard*.  Same robust ruler (modified z-score over the
tool family, Iglewicz-Hoaglin), same honest degenerate cases, one
new meter — so `anomalies --tokens` can flag the context-stuffing
derailment that came back quickly every single time.
"""

import argparse
import json

from approximately.anomaly import (
    TraceTokenAnomaly,
    detect_fleet_token_anomalies,
    detect_token_anomalies,
    summarize_token_anomalies,
)
from approximately.cli import cmd_anomalies
from approximately.mcp_server import ServerContext, handle_request
from approximately.store import TraceStore
from approximately.trace import Step, Trace


def _run(tokens_for_search, ident="run", tool="search"):
    trace = Trace(task="loopy run", id=ident, created_at=1.0)
    for tokens in tokens_for_search:
        trace.add(Step(kind="tool_call", tool=tool,
                       tokens=tokens, latency_ms=50))
    return trace


def test_burn_is_flagged():
    tokens = [110, 95, 105, 90, 100, 115, 85, 120, 108, 92, 9000]
    trace = _run(tokens)
    anomalies = detect_token_anomalies(trace)
    assert len(anomalies) == 1
    a = anomalies[0]
    assert a.tokens == 9000
    assert a.direction == "burn"
    assert a.step_index == 10


def test_frugal_is_flagged_too():
    tokens = [500, 480, 520, 510, 490, 505, 495, 515, 485, 508, 3]
    anomalies = detect_token_anomalies(_run(tokens))
    assert len(anomalies) == 1
    assert anomalies[0].direction == "frugal"


def test_min_samples_is_an_honest_noop():
    trace = _run([100, 9000, 100])
    assert detect_token_anomalies(trace) == []


def test_identical_counts_have_no_scale():
    trace = _run([100] * 12)
    assert detect_token_anomalies(trace) == []


def test_per_tool_baselines_separate_families():
    tokens = [10, 12, 11, 13, 10, 12,            # summarize
              5000, 5100, 4900, 5050, 4950, 5150]  # ingest
    trace = _run(tokens, tool="summarize")
    trace.steps[6].tool = "ingest"
    trace.steps[7].tool = "ingest"
    trace.steps[8].tool = "ingest"
    trace.steps[9].tool = "ingest"
    trace.steps[10].tool = "ingest"
    trace.steps[11].tool = "ingest"
    pooled = detect_token_anomalies(trace)
    assert pooled == []          # one scale hides the other family
    split = detect_token_anomalies(trace, per_tool=True)
    assert split == []           # both families are internally calm


def test_per_tool_catches_cross_family_burn():
    tokens = [10, 12, 11, 13, 10, 12, 5000, 12, 11, 13, 10, 12]
    trace = _run(tokens)
    for i in (6, 7, 8, 9, 10, 11):
        trace.steps[i].tool = "ingest"
    anomalies = detect_token_anomalies(trace, per_tool=True)
    assert [a.tool for a in anomalies] == ["ingest"]
    assert anomalies[0].tokens == 5000


def _fleet():
    traces = [_run([110, 95, 105, 90, 100, 115, 85, 120, 108, 92,
                    9000], ident="loopy")]
    traces.extend(_run([90 + j] * 11, ident=f"calm{j}")
                  for j in range(4))
    return traces


def test_fleet_mode_carries_trace_ids_real():
    fleet = detect_fleet_token_anomalies(_fleet())
    assert fleet
    worst = fleet[0]
    assert isinstance(worst, TraceTokenAnomaly)
    assert worst.trace_id == "loopy"
    assert worst.tokens == 9000
    assert worst.direction == "burn"
    assert all(a.trace_id == "loopy" for a in fleet)


def test_summarize_prose():
    assert summarize_token_anomalies([]) == "no token anomalies"
    tokens = [110, 95, 105, 90, 100, 115, 85, 120, 108, 92, 9000]
    text = summarize_token_anomalies(detect_token_anomalies(_run(tokens)))
    assert "token anomaly" in text
    assert "burn" in text
    assert "9000" in text


def test_cli_tokens_json(tmp_path, capsys):
    store = TraceStore(tmp_path / "s")
    store.save(_run([110, 95, 105, 90, 100, 115, 85, 120, 108, 92,
                     9000], ident="abc123def456"))
    args = argparse.Namespace(store=str(store.directory),
                              trace="abc123def456", tokens=True,
                              per_tool=False, threshold=3.5,
                              all_=False, json=True, since=None)
    args.all = False
    assert cmd_anomalies(args) == 1
    rows = json.loads(capsys.readouterr().out)
    assert rows[0]["tokens"] == 9000
    assert rows[0]["direction"] == "burn"
    assert "latency_ms" not in rows[0]


def test_cli_tokens_fleet(tmp_path, capsys):
    store = TraceStore(tmp_path / "s")
    for trace in _fleet():
        store.save(trace)
    args = argparse.Namespace(store=str(store.directory),
                              trace="loopy", tokens=True,
                              per_tool=False, threshold=3.5,
                              json=True, since=None)
    args.all = True
    assert cmd_anomalies(args) == 1
    rows = json.loads(capsys.readouterr().out)
    assert rows[0]["trace_id"] == "loopy"


def test_cli_latency_output_unchanged(tmp_path, capsys):
    # the latency meter keeps its exact JSON shape (pin against
    # accidental field drift)
    store = TraceStore(tmp_path / "s")
    trace = _run([110, 95, 105, 90, 100, 115, 85, 120, 108, 92, 9000],
                 ident="abc123def456")
    for step in trace.steps:
        step.tokens = 0
        step.latency_ms = 100 + step.index * (5 ** (step.index % 2))
    trace.steps[-1].latency_ms = 90_000
    store.save(trace)
    args = argparse.Namespace(store=str(store.directory),
                              trace="abc123def456", tokens=False,
                              per_tool=False, threshold=3.5,
                              json=True, since=None)
    args.all = False
    assert cmd_anomalies(args) == 1
    rows = json.loads(capsys.readouterr().out)
    assert rows[0]["latency_ms"] == 90_000
    assert "tokens" not in rows[0]


def test_mcp_tokens(tmp_path):
    store = TraceStore(tmp_path / "s")
    store.save(_run([110, 95, 105, 90, 100, 115, 85, 120, 108, 92,
                     9000], ident="abc123def456"))
    payload = handle_request({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "anomalies",
                   "arguments": {"store": str(store.directory),
                                 "trace": "abc123def456",
                                 "tokens": True}},
    }, ServerContext(str(store.directory)))
    result = json.loads(payload["result"]["content"][0]["text"])
    assert result["tokens"] is True
    assert result["count"] == 1
    assert result["anomalies"][0]["tokens"] == 9000
    assert result["summary"].startswith("1 token anomaly")


def test_mcp_tokens_fleet(tmp_path):
    store = TraceStore(tmp_path / "s")
    for trace in _fleet():
        store.save(trace)
    payload = handle_request({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "anomalies",
                   "arguments": {"store": str(store.directory),
                                 "trace": "loopy", "tokens": True,
                                 "fleet": True}},
    }, ServerContext(str(store.directory)))
    result = json.loads(payload["result"]["content"][0]["text"])
    assert result["fleet"] is True
    assert result["tokens"] is True
    assert result["count"] >= 1


def test_fleet_per_model_splits_families(tmp_path):
    # gpt-4o and mini doing the "same" search: pooled, the big
    # model's honest usage looks like burn; split, each model gets
    # its own ruler and the real mini burn is the only flag
    store = TraceStore(tmp_path / "s")
    big = _run([800, 850, 900, 750, 820, 880, 790, 860, 810, 840, 830,
                870], ident="big")
    store.save(big)
    for j in range(4):
        small = _run([50 + j, 45 + j, 55 + j, 48 + j, 52 + j, 60 + j,
                      47 + j, 58 + j, 44 + j, 53 + j, 49 + j, 61 + j],
                     ident=f"mini{j}")
        small.model = "gpt-4o-mini"
        store.save(small)
    burn = _run([50, 48, 52, 47, 51, 55, 49, 53, 46, 54, 50, 6_000],
                ident="mini-burn")
    burn.model = "gpt-4o-mini"
    store.save(burn)
    from approximately.anomaly import detect_fleet_token_anomalies

    traces = store.list_traces()
    pooled = detect_fleet_token_anomalies(traces)
    assert any(a.trace_id == "big" for a in pooled), (
        "pooled scale cries wolf on the big model")

    split = detect_fleet_token_anomalies(traces, per_model=True)
    assert not any(a.trace_id == "big" for a in split), (
        "split: the big family is internally calm")
    mini_flags = [a for a in split if a.trace_id == "mini-burn"]
    assert mini_flags and mini_flags[0].tokens == 6_000
    assert "[gpt-4o-mini]" in mini_flags[0].tool
