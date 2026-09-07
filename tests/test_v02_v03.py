"""v0.2/v0.3 feature tests: framework adapters, judge distillation,
attribution benchmark, cross-trace clustering, budget regressions, curves."""

from __future__ import annotations

import json

import pytest
from fake_openai_server import HAS_OPENAI

from approximately.attributor import attribute
from approximately.cluster import cluster
from approximately.curve import budget_curve, render_curve_html
from approximately.distill import (
    evaluate,
    example_for,
    export_sft,
    load_dataset,
    rules_labeler,
)
from approximately.regress import render_regression
from approximately.trace import TOOL_CALL, Step, Trace

# ---- framework adapters ------------------------------------------------------

def test_langgraph_handler_records_tool_runs():
    pytest.importorskip("langchain_core")
    from langchain_core.tools import tool

    from approximately.contrib.langgraph import ApproximatelyCallbackHandler

    handler = ApproximatelyCallbackHandler("langchain run")

    @tool
    def search_flights(q: str) -> str:
        """search flights"""
        return "JT-044 $880"

    search_flights.invoke({"q": "SFO NRT"},
                          config={"callbacks": [handler]})
    steps = handler.recorder.trace.tool_calls()
    assert len(steps) == 1
    assert steps[0].tool == "search_flights"
    assert "JT-044" in steps[0].result


def test_langgraph_handler_records_tool_errors():
    pytest.importorskip("langchain_core")
    from langchain_core.tools import tool

    from approximately.contrib.langgraph import ApproximatelyCallbackHandler

    handler = ApproximatelyCallbackHandler("langchain run")

    @tool
    def detonate() -> str:
        """always fails"""
        raise ValueError("kaput")

    with pytest.raises(ValueError):
        detonate.invoke({}, config={"callbacks": [handler]})
    (step,) = handler.recorder.trace.tool_calls()
    assert "ValueError" in step.error


def test_agents_sdk_processor_records_function_spans():
    pytest.importorskip("agents")
    from agents.tracing import (
        add_trace_processor,
        function_span,
        get_trace_provider,
        set_trace_processors,
        trace,
    )

    from approximately.contrib.agents_sdk import AgentsSDKProcessor

    provider = get_trace_provider()
    multi = provider._multi_processor
    saved = list(multi._processors)
    processor = AgentsSDKProcessor("agents sdk run")
    add_trace_processor(processor)
    try:
        _drive_spans(function_span, trace)
    finally:
        set_trace_processors(saved)
    steps = processor.recorder.trace.tool_calls()
    assert [s.tool for s in steps] == ["search_flights", "book_flight"]
    assert "JT-044" in steps[0].result
    assert "RuntimeError" in steps[1].error


def _drive_spans(function_span, trace):
    with trace("research"):
        with function_span("search_flights", input='{"q": "SFO NRT"}') as span:
            span.span_data.output = "JT-044 $880"
        with function_span("book_flight", input='{"seat": "12A"}') as span:
            span.set_error("RuntimeError: seat gone")


def test_crewai_adapter_degrades_without_crewai():
    """The adapter imports lazily and registers nothing if crewai is absent."""
    try:
        import crewai  # noqa: F401
        crewai_missing = False
    except ImportError:
        crewai_missing = True

    from approximately.contrib.crewai import record_crew

    rec = record_crew("crew task")
    assert rec.recorder.trace.task == "crew task"
    if crewai_missing:
        assert rec._handlers == []  # registered nothing, did not crash


# ---- judge distillation & benchmark -----------------------------------------

def test_export_sft_shape_is_local_preset(failing_trace, tmp_path):
    out = tmp_path / "sft.jsonl"
    stats = export_sft([failing_trace], out, rules_labeler())
    assert stats["labeled"] == 1 and stats["modes"]["FM-1.3"] == 1
    example = json.loads(out.read_text(encoding="utf-8").splitlines()[0])
    roles = [m["role"] for m in example["messages"]]
    assert roles == ["system", "user", "assistant"]
    system, user, assistant = example["messages"]
    # compact prompt: mode ids present, definitions absent
    assert "FM-1.3" in system["content"]
    assert "unnecessarily redoes" not in system["content"]
    assert json.loads(user["content"])["task"] == failing_trace.task
    assert json.loads(assistant["content"])["mode_id"] == "FM-1.3"


def test_rules_labeler_skips_unsure_traces(clean_trace, tmp_path):
    out = tmp_path / "sft.jsonl"
    stats = export_sft([clean_trace], out, rules_labeler())
    assert stats == {"labeled": 0, "skipped": 1, "modes": {}}


@pytest.mark.skipif(not HAS_OPENAI, reason="openai not installed")
def test_teacher_labeling_via_fake_server(failing_trace, tmp_path, openai_url,
                                          fake_openai):
    from approximately.distill import teacher_labeler

    fake_openai.content = json.dumps(
        {"mode_id": "FM-3.2", "step_index": 4, "confidence": 0.9}
    )
    out = tmp_path / "sft.jsonl"
    stats = export_sft([failing_trace], out,
                       teacher_labeler("teacher-model", base_url=openai_url,
                                       api_key="test"))
    assert stats["modes"] == {"FM-3.2": 1}


def test_benchmark_precision_recall_on_synthetic_dataset():
    def make(mode_tool: str, result: str, success: bool) -> Trace:
        trace = Trace(task=f"run with {result}", success=success)
        trace.add(Step(kind=TOOL_CALL, tool=mode_tool, args={}, result=result))
        trace.add(Step(kind=TOOL_CALL, tool=mode_tool, args={}, result=result))
        trace.add(Step(kind=TOOL_CALL, tool=mode_tool, args={}, result=result))
        trace.add(Step(kind="response", result="final"))
        trace.success = success
        return trace

    def derail_like() -> Trace:
        # too few calls for the derailment rule: predictor falls back to OTHER
        trace = Trace(task="walk the dog", success=False)
        trace.add(Step(kind=TOOL_CALL, tool="stock_trade", args={}, result="x"))
        trace.add(Step(kind="response", result="final"))
        trace.success = False
        return trace

    dataset = [
        (make("search", "r1", False), "FM-1.3"),   # rule hits -> tp
        (make("search", "r2", False), "FM-1.3"),   # rule hits -> tp
        (make("search", "r3", False), "OTHER"),    # gold wrong on purpose: fp + fn
        (derail_like(), "FM-2.3"),                 # rule silent here -> fn
    ]
    result = evaluate(dataset, rules_labeler())
    assert result.accuracy == pytest.approx(0.5)
    fm = result.per_mode["FM-1.3"]
    assert fm["tp"] == 2 and fm["fp"] == 1 and fm["fn"] == 0
    assert result.per_mode["FM-2.3"]["fn"] == 1
    assert result.per_mode["OTHER"]["fn"] == 1
    assert result.summary().startswith("attribution benchmark")


def test_load_dataset_both_formats(tmp_path):
    approx = tmp_path / "approx.jsonl"
    trace = Trace(task="load me", success=False)
    trace.add(Step(kind=TOOL_CALL, tool="search", args={}, result="x"))
    record = trace.to_dict()
    record["label"] = "FM-1.3"
    approx.write_text(json.dumps(record), encoding="utf-8")
    loaded = load_dataset(approx)
    assert len(loaded) == 1 and loaded[0][1] == "FM-1.3"
    assert loaded[0][0].steps[0].tool == "search"

    mast = tmp_path / "mast.jsonl"
    mast.write_text(json.dumps({
        "task": "mast record",
        "trace": [{"role": "user", "content": "book it"},
                  {"role": "function_call", "name": "search", "content": "r"}],
        "label": "FM-3.2",
    }), encoding="utf-8")
    loaded = load_dataset(mast, fmt="mast")
    assert loaded[0][1] == "FM-3.2"
    assert loaded[0][0].steps[1].tool == "search"


def test_agents_sdk_generation_agent_handoff_spans():
    """Unit-test remaining span types with real span-data classes."""
    pytest.importorskip("agents")
    from agents.tracing.span_data import (
        AgentSpanData,
        GenerationSpanData,
        HandoffSpanData,
    )

    from approximately.contrib.agents_sdk import AgentsSDKProcessor

    processor = AgentsSDKProcessor("unit")
    processor.on_trace_start(type("T", (), {"name": "research task"})())
    assert processor.recorder.trace.task == "research task"

    gen = type("S", (), {"span_data": GenerationSpanData(
        model="gpt-5", output=["hi"], usage={"output_tokens": 42}),
        "error": None})()
    processor.on_span_end(gen)
    (llm,) = [s for s in processor.recorder.trace.steps if s.tool == "llm"]
    assert llm.meta["tokens"] == 42

    processor.on_span_end(type("S", (), {"span_data": AgentSpanData(
        name="booker"), "error": None})())
    processor.on_span_end(type("S", (), {"span_data": HandoffSpanData(
        from_agent="a", to_agent="b"), "error": None})())
    kinds = [s.kind for s in processor.recorder.trace.steps]
    assert kinds.count("observation") == 2  # agent + handoff observations


def test_crewai_handlers_dispatch_without_crewai():
    """The event dispatch logic is testable with plain payloads."""
    from approximately.contrib.crewai import CrewAIRecorder

    rec = CrewAIRecorder("crew dispatch")
    rec._on("ToolUsageFinished", None, {"name": "search", "output": "hits"})
    rec._on("ToolUsageError", None, {"name": "search", "error": "boom"})
    rec._on("LLMCallFailed", None, {"error": "rate limited"})
    rec._on("CrewKickoffFailed", None, {"error": "crew died"})

    steps = rec.recorder.trace.steps
    assert steps[0].kind == "tool_call" and steps[0].tool == "search"
    assert steps[1].error == "boom"
    assert rec.recorder.trace.success is False  # kickoff failed
    assert any("crew died" in (s.error or "") for s in steps)


# ---- v0.3: clustering ----------------------------------------------------

def _store_like_traces() -> list:
    def booking_repeat(task: str) -> Trace:
        trace = Trace(task=task, success=False)
        trace.add(Step(kind=TOOL_CALL, tool="search_flights",
                       args={"q": task[-6:]}, result="JT-044"))
        trace.add(Step(kind=TOOL_CALL, tool="search_flights",
                       args={"q": task[-6:]}, result="JT-044"))
        trace.add(Step(kind="response", result="done"))
        trace.success = False
        return trace

    def hotel_crash(task: str) -> Trace:
        trace = Trace(task=task, success=False)
        trace.add(Step(kind=TOOL_CALL, tool="book_hotel", args={}, result="try"))
        trace.add(Step(kind="error", error="TimeoutError: hotel api"))
        trace.success = False
        return trace

    healthy = Trace(task="fine run", success=True)
    healthy.add(Step(kind="response", result="ok"))
    return [booking_repeat(f"booking {i}") for i in range(3)] + [
        hotel_crash("hotel a"), hotel_crash("hotel b"), healthy]


def test_cluster_finds_recidivist_modes():
    report = cluster(_store_like_traces())
    assert report.traces_scanned == 6
    assert report.failures_found == 5
    recidivists = report.recidivists(min_size=2)
    assert len(recidivists) == 2  # FM-1.3 x3 and FM-3.1 x2
    top = report.clusters[0]
    assert top.mode_id == "FM-1.3" and top.size == 3
    assert top.tools == ("search_flights",)
    crash = next(c for c in report.clusters if c.mode_id == "FM-3.1")
    assert crash.size == 2 and crash.tools == ("book_hotel",)
    assert "recidivist clusters" in report.summary(min_size=2)


# ---- v0.3: budget regression guard -----------------------------------------

def test_budget_guard_emitted_and_fails_on_tight_budget(failing_trace,
                                                        tmp_path):
    report = attribute(failing_trace)
    code = render_regression(failing_trace, report, budget=15, min_recall=0.8)
    assert "test_context_budget_recall" in code
    assert "forecast(trace, budget=15" in code
    test_file = tmp_path / "test_budget.py"
    test_file.write_text(code, encoding="utf-8")
    result = pytest.main(["-q", "--no-header", str(test_file), "-k",
                          "budget_recall"])
    assert result != 0  # 15 tokens loses facts -> guard fails


def test_budget_guard_passes_with_generous_budget(failing_trace, tmp_path):
    full = _full_tokens(failing_trace)
    report = attribute(failing_trace)
    code = render_regression(failing_trace, report, budget=full * 4,
                             min_recall=0.8)
    test_file = tmp_path / "test_budget_ok.py"
    test_file.write_text(code, encoding="utf-8")
    result = pytest.main(["-q", "--no-header", str(test_file), "-k",
                          "budget_recall"])
    assert result == 0  # generous budget keeps everything


def _full_tokens(trace):
    from approximately.context import estimate_tokens

    total = sum(estimate_tokens(s.result) + 8 for s in trace.steps if s.result)
    return total + estimate_tokens(trace.task)


# ---- v0.3: curves -----------------------------------------------------------

def test_budget_curve_recall_is_monotone(failing_trace):
    curve = budget_curve(failing_trace)
    assert curve.points, "sweep produced points"
    recalls = [p.recall for p in curve.points]
    assert recalls == sorted(recalls)  # more budget never loses recall
    assert curve.full_tokens > 0
    assert curve.points[-1].recall == pytest.approx(1.0)  # full-ish = perfect


def test_curve_html_contains_svg_and_stats(failing_trace):
    curve = budget_curve(failing_trace)
    html = render_curve_html(curve, scatter=[(100, True), (200, False)])
    assert "<svg" in html and "<polyline" in html
    assert "cost/recall curve".lower() in html.lower() or "budget" in html.lower()
    assert html.startswith("<!doctype html>")


def test_success_vs_tokens_scatter(failing_trace, clean_trace):
    from approximately.curve import success_vs_tokens

    data = success_vs_tokens([failing_trace, clean_trace])
    assert len(data) == 2
    assert {success for _, success in data} == {False, True}
    assert all(tokens > 0 for tokens, _ in data)


def test_distill_example_step_index_points_at_evidence(failing_trace):
    report = attribute(failing_trace)
    example = example_for(failing_trace, "FM-1.3")
    payload = json.loads(example["messages"][2]["content"])
    assert payload["step_index"] == report.detections[0].step_index
