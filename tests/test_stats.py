"""Tests for the stats command and attribute --all batch mode."""

from __future__ import annotations

import json

from approximately.cli import main
from approximately.cluster import store_stats


def test_store_stats_summary(failing_trace, clean_trace):
    stats = store_stats([failing_trace, clean_trace])
    assert stats.traces == 2
    assert stats.failures == 1
    assert stats.failure_rate == 0.5
    assert stats.mode_counts == {"FM-1.3": 1}
    assert "failure rate 50%" in stats.summary()
    assert "top failure modes" in stats.summary()


def test_store_stats_empty():
    stats = store_stats([])
    assert stats.traces == 0 and stats.failure_rate == 0.0
    assert "0 traces" in stats.summary()


def test_cli_stats_json(demo_store, capsys):
    directory, _ = demo_store
    code = main(["stats", "--store", directory, "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["traces"] == 1
    assert payload["failures"] == 1
    assert payload["modes"] == {"FM-1.3": 1}


def test_cli_attribute_all_json(demo_store, capsys):
    directory, _ = demo_store
    code = main(["attribute", "--all", "--store", directory, "--json"])
    results = json.loads(capsys.readouterr().out)
    assert code == 0
    assert len(results) == 1
    assert results[0]["primary_mode"] == "FM-1.3"
    assert results[0]["trace"]["steps"] == 6


def test_cli_cluster_last_n(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("APPROXIMATELY_HOME", str(tmp_path / "traces"))
    from approximately.cli import main

    main(["demo"])
    main(["demo"])
    code = main(["cluster", "--last", "1"])
    out = capsys.readouterr().out
    assert code == 0
    assert "scanned 1 traces" in out


def test_cli_curve_custom_budgets(demo_store, tmp_path, capsys):
    directory, trace_id = demo_store
    code = main(["curve", trace_id, "--store", directory,
                 "--budgets", "50,500,5000", "-o",
                 str(tmp_path / "c.html")])
    out = capsys.readouterr().out
    assert code == 0
    assert "50 ->" in out and "5000 ->" in out


def test_cli_stats_trend(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("APPROXIMATELY_HOME", str(tmp_path / "traces"))
    from approximately.cli import main

    main(["demo"])
    # backdate the trace 8 days so it lands in the previous bucket
    import os
    import time

    trace_file = next((tmp_path / "traces").glob("*.json"))
    past = time.time() - 8 * 86400
    os.utime(trace_file, (past, past))
    trace_file2 = next((tmp_path / "traces").glob("*.report.html"))
    os.utime(trace_file2, (past, past))

    code = main(["stats", "--trend", "--trend-bucket-days", "7"])
    out = capsys.readouterr().out
    assert code == 0
    assert "1 runs, 1 failed (100%)" in out
