"""Context-runtime edge cases and adversarial inputs."""

from __future__ import annotations

import pytest

from approximately.context import (
    ContextRuntime,
    default_facts,
    estimate_tokens,
    forecast,
)


def test_zero_and_negative_budgets_evict_everything_unpinned():
    for budget in (0, -5):
        rt = ContextRuntime(budget=budget, task="t")
        rt.add_tool_result("r1", "some content")
        assert all(i.pinned for i in rt.render()), budget


def test_all_pinned_over_budget_is_honest_state():
    rt = ContextRuntime(budget=1)
    rt.pin("a", "long pinned fact " * 10)
    rt.pin("b", "another long pinned fact " * 10)
    assert rt.used_tokens() > rt.budget  # over budget, nothing silently dropped
    assert len(rt.render()) == 2


def test_compact_with_nothing_evictable_is_noop():
    rt = ContextRuntime(budget=10_000, task="t")
    summary = rt.compact(lambda items: "unused")
    assert summary.text == ""
    assert len(rt.render()) == 1  # just the task


def test_compact_really_shrinks_and_keeps_pins():
    rt = ContextRuntime(budget=10_000, task="research task")
    rt.pin("deadline", "submit by Friday")
    for i in range(5):
        rt.add_tool_result(f"r{i}", "lorem ipsum dolor sit amet " * 20)
    rt.compact(lambda items: f"summary of {len(items)} results")
    assert rt.used_tokens() < 120
    keys = [i.key for i in rt.render()]
    assert "deadline" in keys and "task" in keys
    assert not any(k.startswith("r") for k in keys)


def test_empty_content_tokens_are_at_least_one():
    assert estimate_tokens("") == 1
    assert ContextRuntime(budget=5, task="").used_tokens() == 0


def test_default_facts_skip_errors_and_empty_results(failing_trace):
    facts = default_facts(failing_trace)
    assert facts  # has tool results
    for key, needle in facts.items():
        assert needle.strip()


def test_forecast_on_trace_without_tool_results():
    from approximately.recorder import Recorder

    with Recorder("talk only", save=False) as rec:
        rec.plan("just think")
        rec.respond("done", success=True)
    fc = forecast(rec.trace, budget=10)
    assert fc.final_probe.recall == pytest.approx(1.0)  # no facts -> vacuous pass


def test_forecast_empty_trace():
    from approximately.trace import Trace

    fc = forecast(Trace(task="empty", success=True), budget=100)
    assert fc.steps == []
    assert fc.budgeted_tokens == 0


def test_forecast_step_timeline_tracks_eviction_steps(failing_trace):
    fc = forecast(failing_trace, budget=15)
    evicting_steps = [s.step_index for s in fc.steps if s.evicted_keys]
    assert evicting_steps, "tight budget must evict somewhere"
    assert min(evicting_steps) >= 1  # nothing to evict before the first result


def test_recall_probe_substring_semantics():
    rt = ContextRuntime(budget=10_000, task="t")
    rt.add_tool_result("r", "price is $870 USD total")
    probe = rt.recall_probe({"exact": "$870 USD", "missing": "$871",
                             "partial": "870"})
    assert probe.kept == ["exact", "partial"]
    assert probe.lost == ["missing"]


def test_exact_token_counting_with_tiktoken(monkeypatch):
    tiktoken = pytest.importorskip("tiktoken")
    monkeypatch.setenv("APPROXIMATELY_EXACT_TOKENS", "1")
    import importlib

    from approximately import context

    importlib.reload(context)
    try:
        assert context.estimate_tokens("hello world") >= 1
        assert context.estimate_tokens("") == 1
    finally:
        monkeypatch.delenv("APPROXIMATELY_EXACT_TOKENS")
        importlib.reload(context)
