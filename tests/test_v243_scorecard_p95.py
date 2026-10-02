"""v243: the scorecards speak percentiles; the selection prices itself.

A mean hides the tail — and the tail is where users live.  Both
scorecards gain p95 columns (nearest-rank, same ruler as the
anomaly detectors): per-tool step latency p95 and per-tool token
p95, per-agent latency p95.  Prometheus grows matching gauges.
And `query --stats --prices prices.json` prices the selection:
est_spend over the selected traces, with unpriced models counted
(because a spend you cannot compute is a spend that does not hold
— the ci-gate rule, carried over).
"""

import json

from approximately.cli import main
from approximately.cluster import agent_scorecard, tool_scorecard
from approximately.metrics import render_agent_prometheus
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _seed(path):
    store = TraceStore(path)
    for i in range(6):
        rec = Recorder(f"run {i}", model="gpt-x", store=store,
                       save=False, agent="worker")
        for j, ms in enumerate((100, 110, 105, 108, 102, 4000)):
            rec.tool("search", {"q": j}, tokens=100 + j,
                     latency_ms=ms)
        rec.respond("done", success=i < 5)
        store.save(rec.trace)
    return store


def test_tool_scorecard_p95_columns(tmp_path):
    store = _seed(tmp_path / "s")
    rows = tool_scorecard(store.list_traces())
    row = next(r for r in rows if r["tool"] == "search")
    assert row["p95_ms"] == 4000.0        # the outlier owns the tail
    assert row["p95_tokens"] == 105       # nearest-rank over 6 samples


def test_agent_scorecard_p95_columns(tmp_path):
    store = _seed(tmp_path / "s")
    rows = agent_scorecard(store.list_traces())
    row = rows[0]
    assert row["p95_ms"] == 4000.0
    assert row["p95_tokens"] == 105


def test_scorecard_p95_none_without_samples(tmp_path):
    store = TraceStore(tmp_path / "s")
    rec = Recorder("untimed", save=False)
    rec.observe("just looking")
    rec.respond("done", success=True)
    store.save(rec.trace)
    rows = tool_scorecard(store.list_traces())
    assert rows == []                     # no tool calls, no tool rows
    agents = agent_scorecard(store.list_traces())
    assert all(a["p95_ms"] is None and a["p95_tokens"] is None
               for a in agents)


def test_prometheus_grows_p95_gauges(tmp_path):
    store = _seed(tmp_path / "s")
    tool_scorecard(store.list_traces())
    text = render_agent_prometheus(
        agent_scorecard(store.list_traces()))
    assert "approximately_agent_p95_latency_ms" in text
    assert "approximately_agent_p95_tokens" in text
    assert "# TYPE approximately_agent_p95_tokens gauge" in text


def test_stats_by_tool_table_shows_p95(tmp_path, capsys):
    _seed(tmp_path / "s")
    code = main(["stats", "--store", str(tmp_path / "s"),
                 "--by-tool"])
    assert code == 0
    out = capsys.readouterr().out
    assert "p95ms" in out and "p95tok" in out
    assert "4000" in out


def test_query_stats_prices_the_selection(tmp_path, capsys):
    _seed(tmp_path / "s")
    prices = tmp_path / "prices.json"
    prices.write_text(json.dumps({"gpt-x": 3.0}), encoding="utf-8")
    code = main(["query", "--store", str(tmp_path / "s"),
                 "success == true", "--stats",
                 "--prices", str(prices)])
    assert code == 0
    out = capsys.readouterr().out
    # 5 successful runs x 6 steps x ~102 tokens ≈ 3k tokens @ $3/1k
    assert "est spend $" in out


def test_query_stats_json_carries_spend(tmp_path, capsys):
    _seed(tmp_path / "s")
    prices = tmp_path / "prices.json"
    prices.write_text(json.dumps({"gpt-x": 1.0}), encoding="utf-8")
    code = main(["query", "--store", str(tmp_path / "s"),
                 "success == true", "--stats", "--json",
                 "--prices", str(prices)])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["est_spend"] > 0
    assert payload["unpriced_tokens"] == 0
