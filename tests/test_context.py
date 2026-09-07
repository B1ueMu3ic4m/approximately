import pytest

from approximately.context import (
    ContextRuntime,
    default_facts,
    estimate_tokens,
    forecast,
)
from approximately.trace import TOOL_CALL


def test_budget_enforcement_evicts_oldest_tool_result_first():
    # task ~3 tokens; each result ~10 tokens; budget fits task+r1+r2, not r3
    rt = ContextRuntime(budget=25, task="do the thing")
    rt.add_tool_result("r1", "a" * 40)
    rt.add_tool_result("r2", "b" * 40)
    rt.add_tool_result("r3", "c" * 40)  # pushes over budget -> r1 evicted
    keys = [i.key for i in rt.render()]
    assert "r1" not in keys and "r2" in keys and "r3" in keys
    assert rt.evictions[0].item_key == "r1"


def test_pins_are_never_evicted():
    rt = ContextRuntime(budget=10, task="the pinned task")
    rt.pin("budget-cap", "$900 hard cap")
    rt.add_tool_result("r1", "y" * 200)  # way over budget
    keys = [i.key for i in rt.render()]
    assert "task" in keys and "budget-cap" in keys
    # everything unpinned is gone
    assert all(i.pinned for i in rt.render())


def test_recall_probe_detects_lost_fact():
    rt = ContextRuntime(budget=10_000, task="book flights")
    rt.add_tool_result("search", "JT-044 $870 window seat available")
    probe = rt.recall_probe({"cheapest": "JT-044 $870", "seatmap": "12A confirmed"})
    assert probe.kept == ["cheapest"]
    assert probe.lost == ["seatmap"]
    assert probe.recall == pytest.approx(0.5)


def test_compact_folds_evictable_items():
    rt = ContextRuntime(budget=10_000, task="research task")
    rt.pin("key-fact", "the deadline is Friday")
    rt.add_tool_result("r1", "lorem " * 30)
    rt.add_tool_result("r2", "ipsum " * 30)
    summary = rt.compact(lambda items: "saw 2 results; nothing important")
    assert summary.kind == "summary"
    keys = [i.key for i in rt.render()]
    assert keys == ["task", "key-fact", summary.key]
    assert rt.used_tokens() < estimate_tokens("lorem " * 30) * 2


def test_forecast_on_recorded_trace(failing_trace):
    facts = default_facts(failing_trace)
    assert facts, "probe facts derived from tool results"
    big = forecast(failing_trace, budget=100_000, facts=facts)
    assert big.final_recall == pytest.approx(1.0)
    assert big.evicted_count == 0

    tight = forecast(failing_trace, budget=15, facts=facts)
    assert tight.evicted_count > 0
    assert tight.final_recall < 1.0
    assert tight.final_probe.lost, "tight budget loses facts"
    assert tight.full_context_tokens > tight.budgeted_tokens


def test_forecast_does_not_mutate_trace(failing_trace):
    before = failing_trace.to_dict()
    forecast(failing_trace, budget=1)
    assert failing_trace.to_dict() == before


def test_step_forecast_timeline(failing_trace):
    fc = forecast(failing_trace, budget=10_000)
    tools = [s.tool for s in fc.steps if s.tool]
    assert "search_flights" in tools and "book_flight" in tools
