"""Regression tests for the judge-visibility, store-warning, and demo-consistency fixes."""

from __future__ import annotations

import json

from approximately.demo_multiagent import run_demo as run_crew_demo
from approximately.recorder import Recorder


def test_judge_compact_trace_includes_semantic_meta(failing_trace):
    from approximately.judge import _compact_trace

    payload = json.dumps(_compact_trace(failing_trace))
    parsed = json.loads(payload)
    book_step = next(s for s in parsed["steps"] if s["tool"] == "book_flight")
    assert book_step["meta"]["mutating"] is True


def test_store_warns_on_corrupt_trace(store, capsys):
    (store.directory / "corrupt.json").write_text("{broken", encoding="utf-8")
    traces = store.list_traces()
    captured = capsys.readouterr()
    assert traces == []
    assert "skipping unreadable trace corrupt.json" in captured.err


def test_crew_demo_prices_are_consistent():
    """The demo narrative must not contradict itself across steps."""
    trace, _report, _ = run_crew_demo(store_dir=None)
    results = " ".join(s.result for s in trace.steps)
    # booking demo artifact: price drift must be reflected in the response
    assert "$870" not in results or "880" in results


def test_booking_demo_response_matches_final_price():
    from approximately.demo import _run_booking_agent

    with Recorder("demo", save=False) as rec:
        _run_booking_agent(rec)
    response = rec.trace.final_output or ""
    searches = [s.result for s in rec.trace.steps if s.tool == "search_flights"]
    final_price = searches[-1].split("$")[1].split()[0]
    assert final_price in response, (
        "demo response quotes a price that no longer matches the last search"
    )
