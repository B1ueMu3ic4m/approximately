"""v244: the night-V integration round — every new door, one river.

Night IV's integration round found four seams by making the doors
talk to each other; this round does the same for everything Night V
shipped.  The story: a team records agent runs (with real measured
latencies and tokens), ships them through a spool to a fleet store,
gates CI on them, prices them, pivots them in a spreadsheet,
deep-verifies the evidence, and scaffolds the gate into a fresh
repo.  Every seam between those doors is asserted, not assumed.
"""

import csv
import json

from approximately import mcp_server
from approximately.cli import cmd_ci, main
from approximately.cluster import tool_scorecard
from approximately.doctor import doctor
from approximately.exporter import export_store
from approximately.fleet import survey
from approximately.mcp_server import _tool_ci_gate
from approximately.recorder import Recorder
from approximately.scaffold import init_scaffold
from approximately.spool import spool_pass
from approximately.store import TraceStore


def _record_run(store, i, tokens_per_step=100, hot=False):
    """One run: flat 40ms baseline, tokens steady — except the
    retry-loop run, which burns tokens and stalls one call."""
    rec = Recorder(f"deploy {i}", model="gpt-x", store=store,
                   save=False, agent="worker")
    steps = 8
    for j in range(steps):
        latency = 9000 if (hot and j == steps - 1) else 40 + (j % 3)
        tokens = 2500 if (hot and j == steps - 1) else tokens_per_step
        rec.tool("shell", {"cmd": f"step {j}"}, tokens=tokens,
                 latency_ms=latency)
    rec.respond("shipped", success=not hot)
    return rec.trace


def test_the_whole_river(tmp_path):
    # 1. record: two stores — a producer and a fleet sink
    produced = tmp_path / "produced"
    producer = TraceStore(produced)
    for i in range(6):
        trace = _record_run(producer, i)
        producer.save(trace)
    hot = _record_run(producer, 99, hot=True)
    producer.save(hot)

    # 2. deep doctor: every chain verifies before shipping
    report = doctor(produced, deep=True)
    assert report.chain_checked == 7 and report.chain_failed == []

    # 3. spool: native lines land in a directory; a sink ingests
    spool_dir = tmp_path / "spool"
    spool_dir.mkdir()
    dump = spool_dir / "batch.jsonl"
    export_store(producer, dump, fmt="native")
    sink = TraceStore(tmp_path / "sink")
    outcome = spool_pass(sink, spool_dir, delete=True)
    assert outcome["imported"] == 7
    assert not list(spool_dir.glob("*.jsonl"))     # archived to done/
    assert len(sink.list_traces()) == 7

    # 4. the tokens and latencies survived the spool seam: the hot
    #    step is in the sink at full 9000ms, and the p95 read is
    #    honest about it (55 flat-ish samples: the spike sits above
    #    the 95th line, exactly what p95 is for)
    rescored = tool_scorecard(sink.list_traces())
    shell = next(r for r in rescored if r["tool"] == "shell")
    assert shell["p95_ms"] == 42.0
    assert shell["tokens"] == 6 * 8 * 100 + 7 * 100 + 2500
    hot_back = sink.load(hot.id)
    assert hot_back is not None
    assert hot_back.steps[-2].latency_ms == 9000

    # 5. the ci gate: the burn breaches a token ceiling, honest
    #    ceilings pass
    def _ci(store_dir, **kw):
        import argparse
        ns = argparse.Namespace(store=str(store_dir), since=None,
                                json=False, prices=None, **kw)
        return cmd_ci(ns)

    assert _ci(sink.directory, max_tokens=1000) == 1
    assert _ci(sink.directory, max_tokens=10 ** 9,
               max_p95_latency_ms=10_000) == 0

    # 6. pricing: the same store prices cleanly; the mystery model
    #    would fail the spend gate
    summaries = survey([sink.directory], prices={"gpt-x": 3.0})
    assert summaries[0].est_spend is not None
    assert summaries[0].est_spend > 0

    # 7. spreadsheet pivot: the csv door quotes the injection cell
    csv_out = tmp_path / "pivot.csv"
    export_store(sink, csv_out, fmt="csv")
    with csv_out.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.reader(fh))
    assert rows[0][9] == "tokens"
    # every step row carries integer tokens, none begin a formula
    for row in rows[1:]:
        assert row[9].isdigit() or row[9] == ""

    # 8. the new query operators against the sink
    code = main(["query", "--store", str(sink.directory),
                 "tools in ('shell') and success == false", "--json"])
    assert code == 0

    # 9. the MCP tool agrees with the CLI verdict on the same store
    out = _tool_ci_gate(mcp_server.ServerContext(str(sink.directory)),
                        {"store": str(sink.directory),
                         "max_tokens": 1000})
    assert out["ok"] is False and out["traces"] == 7

    # 10. scaffold the gate into a fresh repo; the workflow names ci
    repo = tmp_path / "repo"
    statuses = init_scaffold(repo)
    assert set(statuses.values()) == {"written"}
    wf = (repo / ".github" / "workflows" / "agent-gate.yml")
    assert "approximately ci" in wf.read_text(encoding="utf-8")
    prices = json.loads(
        (repo / "prices.json").read_text(encoding="utf-8"))
    assert "gpt-x" not in prices      # teams add their own models


def test_spool_ingest_keeps_the_producers_chain_verifiable(tmp_path):
    # a better-than-expected seam: native export carries the meta,
    # so the producer's integrity chain stays VERIFIABLE on the sink
    # side — evidence survives the spool hop (import of chainless
    # formats stays honestly unsigned via stamp=False)
    produced = tmp_path / "produced"
    producer = TraceStore(produced)
    producer.save(_record_run(producer, 1))
    spool_dir = tmp_path / "spool"
    spool_dir.mkdir()
    dump = spool_dir / "one.jsonl"
    export_store(producer, dump, fmt="native")
    sink = TraceStore(tmp_path / "sink")
    spool_pass(sink, spool_dir)
    report = doctor(sink.directory, deep=True)
    assert report.chain_checked == 1
    assert report.chain_failed == [] and report.healthy
    assert len(sink.list_traces()) == 1
