"""Tests for the postmortem index page, embedded context card,
A/B replay comparison, and the CLI wiring for both."""

from __future__ import annotations

import pytest

from approximately.attributor import attribute
from approximately.cli import main
from approximately.recorder import Recorder
from approximately.replayer import compare, replay
from approximately.report import render_html, render_index_html
from approximately.trace import Step


def test_index_page_lists_traces_with_verdicts(failing_trace, clean_trace,
                                               tmp_path):
    items = [
        (failing_trace, attribute(failing_trace)),
        (clean_trace, attribute(clean_trace)),
    ]
    html = render_index_html(items)
    assert html.startswith("<!doctype html>")
    assert failing_trace.id in html and clean_trace.id in html
    assert "FM-1.3" in html          # failing verdict
    assert "passed" in html          # healthy verdict badge
    assert "2 traces" in html
    assert ".report.html" in html    # links to individual reports


def test_index_page_empty_store(tmp_path):
    html = render_index_html([])
    assert "no traces yet" in html


def test_report_embeds_half_budget_context_card(failing_trace):
    html = render_html(failing_trace, attribute(failing_trace))
    assert "half-budget forecast" in html
    assert "effective recall" in html
    assert "lost facts" in html or "none" in html


def test_replayer_compare_summarizes_ab_difference(failing_trace):
    def broken(step):
        return "totally different output"

    def fixed(step):
        return step.result

    a = replay(failing_trace, broken)
    b = replay(failing_trace, fixed)
    text = compare(a, b)
    assert "diverged -> consistent" in text
    assert "changed steps" in text


def test_replayer_compare_no_change(failing_trace):
    a = replay(failing_trace, lambda s: s.result)
    b = replay(failing_trace, lambda s: s.result)
    text = compare(a, b)
    assert "no per-step changes" in text


def test_cli_replay_patched_flag(demo_store, tmp_path, capsys):
    directory, trace_id = demo_store
    import sys
    from pathlib import Path as _Path

    exec_mod = tmp_path / "orig_exec.py"
    exec_mod.write_text("def execute(step):\n    return step.result\n",
                        encoding="utf-8")
    patched = tmp_path / "patched_exec.py"
    patched.write_text("def execute(step):\n    return 'patched away'\n",
                       encoding="utf-8")
    old = sys.path[:]
    sys.path.insert(0, str(tmp_path))
    try:
        code = main(["replay", trace_id, "--store", directory,
                     "--executor", "orig_exec:execute",
                     "--patched", "patched_exec:execute"])
    finally:
        sys.path[:] = old
    out = capsys.readouterr().out
    assert code == 0
    assert "A/B replay:" in out
    assert "original:" in out and "patched:" in out


def test_recorder_fail_sets_latency(store):
    with Recorder("fail latency", store=store) as rec:
        rec.fail("boom")
    assert rec.trace.steps[-1].latency_ms >= 0


def test_report_all_generates_individual_reports(tmp_path, monkeypatch,
                                                 capsys):
    """Index links must resolve: --all writes every individual report."""
    monkeypatch.setenv("APPROXIMATELY_HOME", str(tmp_path / "traces"))
    from approximately.cli import main

    main(["demo"])
    code = main(["report", "--all"])
    assert code == 0
    out = capsys.readouterr().out
    assert "0 individual reports generated" in out  # demo already wrote its own

    # a trace with no individual report yet gets one
    from approximately.store import TraceStore

    store = TraceStore(tmp_path / "traces")
    (store.directory / "manual.json").write_text(
        __import__("approximately.trace", fromlist=["Trace"])
        .Trace(task="no report yet", success=True).to_json(),
        encoding="utf-8",
    )
    code = main(["report", "--all"])
    out = capsys.readouterr().out
    assert code == 0
    assert "1 individual reports generated" in out
    assert (store.directory / "manual.report.html").exists()
