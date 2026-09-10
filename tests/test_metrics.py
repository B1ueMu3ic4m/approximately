"""Prometheus export: format, escaping, wiring."""

from __future__ import annotations

import re

from approximately.cluster import store_stats
from approximately.metrics import escape_label, render_prometheus
from approximately.recorder import Recorder


def test_escape_label_prometheus_rules():
    assert escape_label('back\\slash') == 'back\\\\slash'
    assert escape_label('say "hi"') == 'say \\"hi\\"'
    assert escape_label("line\nbreak") == "line\\nbreak"


def test_render_contains_help_type_and_samples(store):
    with Recorder("sample run", store=store) as rec:
        rec.tool("search", {}, result="ok")
        rec.fail("boom")
    stats = store_stats(store.list_traces())
    text = render_prometheus(stats)
    assert "# HELP approximately_runs_total" in text
    assert "# TYPE approximately_failure_rate gauge" in text
    assert re.search(r"^approximately_runs_total 1$", text, re.M)
    assert re.search(r"^approximately_failures_total 1$", text, re.M)
    assert "approximately_mode_count" in text


def test_render_escapes_untrusted_task_labels(store):
    with Recorder('task with "quotes" and \\ backslash', store=store) as rec:
        rec.fail("x")
    stats = store_stats(store.list_traces())
    text = render_prometheus(stats, extra_labels={"task": rec.trace.task})
    assert '\\"quotes\\"' in text
    assert "\\\\ backslash" in text
    # no raw newline inside a sample line
    sample_lines = [line for line in text.splitlines()
                    if line.startswith("approximately_")]
    assert all("\n" not in line for line in sample_lines)


def test_cli_metrics_prometheus(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("APPROXIMATELY_HOME", str(tmp_path / "t"))
    from approximately.cli import main

    main(["demo"])
    code = main(["metrics", "--prometheus"])
    out = capsys.readouterr().out
    assert code == 0
    assert "# TYPE approximately_failure_rate gauge" in out
    assert re.search(r"approximately_runs_total \d+", out)
