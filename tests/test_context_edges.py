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
    for needle in facts.values():
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
    pytest.importorskip("tiktoken")
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


# ---- minimal-budget optimizer ------------------------------------------------

def test_optimize_finds_lossless_minimum(failing_trace):
    from approximately.context import default_facts, forecast, optimize_budget

    result = optimize_budget(failing_trace, min_recall=1.0)
    assert result is not None
    # the found budget must actually achieve the target recall
    check = forecast(failing_trace, budget=result.minimal_budget,
                     facts=default_facts(failing_trace))
    assert check.final_probe.recall == pytest.approx(1.0)
    # and one token less must NOT (that's what makes it minimal)
    tighter = forecast(failing_trace, budget=result.minimal_budget - 1,
                       facts=default_facts(failing_trace))
    assert tighter.final_probe.recall < 1.0
    assert result.tokens_saved > 0
    assert result.probes <= 12  # binary search: log2(full) probes, not a sweep


def test_optimize_relaxed_target_saves_more(failing_trace):
    from approximately.context import optimize_budget

    strict = optimize_budget(failing_trace, min_recall=1.0)
    loose = optimize_budget(failing_trace, min_recall=0.5)
    assert loose.minimal_budget <= strict.minimal_budget


def test_optimize_no_facts_returns_none():
    from approximately.context import optimize_budget
    from approximately.recorder import Recorder

    with Recorder("plan only", save=False) as rec:
        rec.plan("just think")
    assert optimize_budget(rec.trace, min_recall=1.0) is None


def test_cli_optimize(demo_store, capsys):
    directory, trace_id = demo_store
    from approximately.cli import main

    code = main(["optimize", trace_id, "--store", directory,
                 "--min-recall", "0.5"])
    out = capsys.readouterr().out
    assert code == 0
    assert "minimal budget" in out and "saves" in out
