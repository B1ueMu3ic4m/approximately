"""Night VII, round 3: the third meter — result bloat.

Latency and tokens had robust-z meters; the size of what a tool
DUMPS INTO THE CONTEXT did not.  A tool returning a 40k-character
wall may be cheap in tokens and fast — and still eat the window.
``anomalies --results`` meters result character length; the report
renders the card.
"""

import json

from approximately.anomaly import (
    detect_fleet_result_anomalies,
    detect_result_anomalies,
    summarize_result_anomalies,
)
from approximately.attributor import attribute
from approximately.cli import main
from approximately.recorder import Recorder
from approximately.report import render_html
from approximately.store import TraceStore


def _noisy_store(tmp_path):
    store = TraceStore(tmp_path / "s")
    with Recorder("bloat run", model="m/1", store=store,
                  save=False) as rec:
        for i in range(5):
            rec.tool("list", {"i": i}, result="x" * 200)
        rec.tool("dump_all", {}, result="y" * 20_000)
        rec.respond("done", success=True)
    store.save(rec.trace)
    return store, rec.trace


def test_detects_the_wall(tmp_path):
    _, trace = _noisy_store(tmp_path)
    anomalies = detect_result_anomalies(trace)
    assert anomalies
    assert anomalies[0].tool == "dump_all"
    assert anomalies[0].result_chars == 20_000
    assert anomalies[0].direction == "bloat"


def test_uniform_results_have_no_scale(tmp_path):
    store = TraceStore(tmp_path / "s")
    with Recorder("uniform", model="m/1", store=store,
                  save=False) as rec:
        for _ in range(6):
            rec.tool("t", {}, result="same")
        rec.respond("done", success=True)
    assert detect_result_anomalies(rec.trace) == []


def test_too_few_samples_is_honest_no_op(tmp_path):
    store = TraceStore(tmp_path / "s")
    with Recorder("tiny", model="m/1", store=store,
                  save=False) as rec:
        rec.tool("a", {}, result="x" * 100)
        rec.tool("b", {}, result="y" * 99_000)
        rec.respond("done", success=True)
    assert detect_result_anomalies(rec.trace) == []


def test_fleet_view_carries_trace_ids(tmp_path):
    store, trace = _noisy_store(tmp_path)
    flags = detect_fleet_result_anomalies(store.list_traces())
    assert flags
    assert all(f.trace_id == trace.id for f in flags)


def test_summarize_names_the_worst(tmp_path):
    _, trace = _noisy_store(tmp_path)
    line = summarize_result_anomalies(
        detect_result_anomalies(trace))
    assert "dump_all" in line
    assert "20,000 chars" in line
    assert "bloat" in line


def test_anomalies_door_lists_results(tmp_path, capsys):
    store, _ = _noisy_store(tmp_path)
    # the door's verdict convention: anomalies FOUND exits 1
    rc = main(["anomalies", "latest", "--store",
               str(store.directory), "--results", "--all"])
    out = capsys.readouterr().out
    assert rc == 1
    assert "dump_all" in out


def test_anomalies_door_json(tmp_path, capsys):
    store, _ = _noisy_store(tmp_path)
    rc = main(["anomalies", "latest", "--store",
               str(store.directory), "--results", "--all", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 1  # findings, not silence
    assert all(row["result_chars"] >= 1 for row in payload)
    assert any(row["tool"] == "dump_all" for row in payload)


def test_report_renders_the_bloat_card(tmp_path):
    _, trace = _noisy_store(tmp_path)
    html = render_html(trace, attribute(trace))
    assert "Result bloat" in html
    assert "20,000 chars" in html


def test_clean_run_has_no_card(tmp_path):
    store = TraceStore(tmp_path / "s")
    with Recorder("calm", model="m/1", store=store,
                  save=False) as rec:
        for i in range(6):
            rec.tool("t", {}, result="x" * 100)
        rec.respond("done", success=True)
    html = render_html(rec.trace, attribute(rec.trace))
    assert "Result bloat" not in html
