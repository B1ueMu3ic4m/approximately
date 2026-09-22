"""v79: per-agent observability — Prometheus agent counters, recidivist
agent clustering, and the metrics --label k=v crash fix.

The label crash is pre-existing: the CLI passed a list of "k=v"
strings where the renderers expect a dict, so any
`metrics --prometheus --label k=v` invocation died with AttributeError.
"""

import json

from approximately.cli import build_parser
from approximately.cluster import agent_scorecard
from approximately.metrics import escape_label, render_agent_prometheus
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _store(tmp_path):
    store = TraceStore(str(tmp_path / "s"))
    for i, ok in enumerate([True, False]):
        rec = Recorder(f"task {i}", save=False, agent="worker")
        rec.tool("bash", {"cmd": f"c{i}"}, result="ok" if ok else "",
                 error=None if ok else "boom")
        rec.respond("done", success=ok)
        store.save(rec.trace)
    return store


def test_escape_label_handles_quotes_and_newlines():
    assert escape_label('a"b') == 'a\\"b'


def test_render_agent_prometheus_has_all_series():
    rec = Recorder("t", save=False, agent="worker")
    rec.tool("bash", {"cmd": "x"}, result="y", error="e")
    rows = agent_scorecard([rec.trace])
    text = render_agent_prometheus(rows)
    for metric in ("approximately_agent_steps_total",
                   "approximately_agent_tool_calls_total",
                   "approximately_agent_errors_total",
                   "approximately_agent_tokens_total",
                   "approximately_agent_failed_traces_total",
                   "approximately_agent_failure_rate"):
        assert f"# TYPE {metric}" in text
        assert '{agent="worker"}' in text
    assert "0.000000" in text  # failure_rate formatting


def test_render_agent_prometheus_extra_labels_and_escaping():
    rows = [{"agent": 'a"g', "steps": 1, "tool_calls": 0, "errors": 0,
             "tokens": 0, "failed_traces": 0, "failure_rate": 0.0}]
    text = render_agent_prometheus(rows, extra_labels={"env": "prod"})
    assert 'agent="a\\"g",env="prod"' in text


def test_cli_metrics_by_agent_prometheus(tmp_path, capsys):
    parser = build_parser()
    args = parser.parse_args(["metrics", "--store",
                              str(_store(tmp_path).directory),
                              "--prometheus", "--by-agent",
                              "--label", "env=prod"])
    assert args.func(args) == 0
    out = capsys.readouterr().out
    assert 'agent="worker",env="prod"' in out
    assert "approximately_agent_steps_total" in out


def test_cli_metrics_label_bug_regression(tmp_path, capsys):
    # pre-existing crash: list of k=v strings hit a dict API
    parser = build_parser()
    args = parser.parse_args(["metrics", "--store",
                              str(_store(tmp_path).directory),
                              "--prometheus", "--label", "env=prod"])
    assert args.func(args) == 0
    assert 'env="prod"' in capsys.readouterr().out


def test_cli_metrics_bad_label_exits_with_error(tmp_path):
    parser = build_parser()
    args = parser.parse_args(["metrics", "--store",
                              str(_store(tmp_path).directory),
                              "--prometheus", "--label", "novalue"])
    try:
        args.func(args)
        raised = False
    except SystemExit as exc:
        raised = "k=v" in str(exc)
    assert raised


def test_cli_cluster_by_agent(tmp_path, capsys):
    store = _store(tmp_path)
    parser = build_parser()
    args = parser.parse_args(["cluster", "--store", str(store.directory),
                              "--by-agent", "--min-size", "1"])
    assert args.func(args) == 0
    assert "recidivist agents" in capsys.readouterr().out

    args = parser.parse_args(["cluster", "--store", str(store.directory),
                              "--by-agent", "--json", "--min-size", "1"])
    assert args.func(args) == 0
    rows = json.loads(capsys.readouterr().out)
    assert rows[0]["agent"] == "worker"
    assert rows[0]["failed_traces"] == 1
