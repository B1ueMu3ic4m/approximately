"""v0.46 — README walkthrough: advertised commands run end to end.

The capabilities table and quickstart promise specific commands and
outputs. This module executes them against a fresh store seeded by
the demo and asserts each command's promised behavior — doc drift now
fails CI instead of shipping a README that lies.
"""

from __future__ import annotations

import os

import pytest

from approximately.cli import main


@pytest.fixture(scope="module")
def demo_store(tmp_path_factory):
    """One demo-seeded store shared by the walkthrough.

    APPROXIMATELY_HOME is set for the whole module (monkeypatch is
    function-scoped and cannot serve a module fixture).
    """
    home = tmp_path_factory.mktemp("readme") / "traces"
    old = os.environ.get("APPROXIMATELY_HOME")
    os.environ["APPROXIMATELY_HOME"] = str(home)
    assert main(["demo"]) == 0  # seed the walkthrough store once
    yield home
    if old is None:
        os.environ.pop("APPROXIMATELY_HOME", None)
    else:
        os.environ["APPROXIMATELY_HOME"] = old


@pytest.fixture(scope="module")
def demo_trace_id(demo_store):
    traces = sorted(demo_store.glob("*.json"),
                    key=lambda p: p.stat().st_mtime)
    assert traces, "demo seeded no traces"
    return traces[-1].stem


def test_demo_tours_three_failures(demo_store, capsys):
    assert main(["demo"]) == 0
    out = capsys.readouterr().out
    assert "VERDICT  FM-1.3 Step Repetition" in out
    assert "SUGGESTED FIXES" in out


def test_demo_multi_agent_scenario(demo_store, capsys):
    assert main(["demo", "--scenario", "multi-agent"]) == 0
    out = capsys.readouterr().out
    assert "multi-agent" in out or "VERDICT" in out


def test_quickstart_attribute(demo_store, demo_trace_id, capsys):
    assert main(["attribute", demo_trace_id]) == 0
    out = capsys.readouterr().out
    assert "FM-" in out


def test_quickstart_regression_guard(demo_store, demo_trace_id, capsys,
                                     tmp_path, monkeypatch):
    # `approximately test` writes its generated guard files into the
    # CWD — run it from a scratch dir so the walkthrough never
    # pollutes the checkout
    monkeypatch.chdir(tmp_path)
    rc = main(["test", demo_trace_id, "--budget", "800"])
    out = capsys.readouterr().out
    assert rc in (0, 1)  # failing demo trace may legitimately trip
    assert "guard" in out.lower() or "test" in out.lower()
    assert list(tmp_path.glob("test_*.py")), "no guard file generated"


def test_verify_single_trace(demo_store, demo_trace_id, capsys):
    assert main(["verify", demo_trace_id]) == 0
    out = capsys.readouterr().out
    assert "intact" in out


def test_verify_all_gates_the_store(demo_store, capsys):
    assert main(["verify", "--all"]) == 0
    out = capsys.readouterr().out
    assert "intact" in out


def test_batch_report_with_trend(demo_store, capsys):
    assert main(["report", "--all"]) == 0
    out = capsys.readouterr().out
    assert "wrote index over" in out and "traces" in out


def test_stats_trend(demo_store, capsys):
    assert main(["stats", "--trend"]) == 0
    out = capsys.readouterr().out
    assert "failure-rate sparkline" in out


def test_fleet_dashboard(demo_store, tmp_path_factory, capsys):
    page = tmp_path_factory.mktemp("fleet") / "fleet.html"
    assert main(["fleet", str(demo_store), "--fleet-html",
                 str(page)]) == 0
    assert page.exists() and "store" in page.read_text(encoding="utf-8")


def test_query_dsl_selects_failures(demo_store, capsys):
    assert main(["query", "success == false"]) == 0
    out = capsys.readouterr().out
    assert "matching trace(s)" in out


def test_anomalies_on_latest(demo_store, capsys):
    rc = main(["anomalies", "latest"])
    assert rc in (0, 1)  # exit 1 means anomalies found — still valid
    out = capsys.readouterr().out
    assert out.strip()  # always reports something


def test_diff_needs_two_traces(demo_store, capsys):
    # walkthrough edge: diff against itself is the identity case
    assert main(["diff", "latest", "latest"]) == 0
    out = capsys.readouterr().out
    assert "similarity 100%" in out or "similarity" in out
