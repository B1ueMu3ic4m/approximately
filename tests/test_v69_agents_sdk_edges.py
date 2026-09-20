"""v0.69 — agents_sdk adapter edge dispatch, pinned directly."""

from __future__ import annotations

from approximately.contrib.agents_sdk import AgentsSDKProcessor


def _span(span_data, error=None, span_id="x"):
    class Span:
        pass

    s = Span()
    s.span_data = span_data
    s.error = error
    return s


class FunctionSpanData:
    name = "web_search"
    input = None
    output = None


class GenerationSpanData:
    model = "gpt-fake"
    output = "thinking..."
    usage = None


class AgentSpanData:
    name = "researcher"


class HandoffSpanData:
    from_agent = "researcher"
    to_agent = "writer"


class ResponseSpanData:
    class response:
        output_text = "final answer text"


def test_span_without_data_is_ignored():
    proc = AgentsSDKProcessor("t")

    class Span:
        span_data = None

    proc.on_span_end(Span())
    assert proc.recorder.trace.steps == []


def test_unknown_span_type_is_ignored():
    proc = AgentsSDKProcessor("t")

    class MysterySpanData:
        pass

    proc.on_span_end(_span(MysterySpanData()))
    assert proc.recorder.trace.steps == []


def test_handoff_span_recorded():
    proc = AgentsSDKProcessor("handoff task")
    proc.on_span_end(_span(HandoffSpanData()))
    observes = [s for s in proc.recorder.trace.steps if s.kind == "observation"]
    assert any("researcher -> writer" in s.result for s in observes)


def test_response_span_captures_final_output():
    proc = AgentsSDKProcessor("response task")
    proc.on_span_end(_span(ResponseSpanData()))
    proc.respond()
    assert proc.recorder.trace.success is True
    response = proc.recorder.trace.steps[-1]
    assert "final answer text" in response.result


def test_unserializable_input_falls_back_to_preview():
    # subclassing renames the type and dodges the handler registry,
    # so the mutation happens on the instance instead
    data = FunctionSpanData()
    data.input = object()
    proc = AgentsSDKProcessor("unserializable")
    proc.on_span_end(_span(data, error=None))
    step = proc.recorder.trace.steps[0]
    assert step.args.get("input"), "preview fallback expected"


def test_generation_without_usage_records_zero_tokens():
    proc = AgentsSDKProcessor("generation")
    proc.on_span_end(_span(GenerationSpanData(), error=None))
    llm = next(s for s in proc.recorder.trace.steps if s.tool == "llm")
    assert llm.tokens == 0


def test_report_returns_failure_report():
    proc = AgentsSDKProcessor("report task")
    proc.on_span_end(_span(FunctionSpanData(), error=None))
    proc.respond("done", success=True)
    report = proc.report()
    assert report.trace_id == proc.recorder.trace.id
