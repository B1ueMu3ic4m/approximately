"""v0.10: LlamaIndex Dispatcher span handler — faked spans, no install."""

from __future__ import annotations

from typing import ClassVar

import pytest

from approximately.contrib.llamaindex import ApproximatelySpanHandler


def _span(kind, **fields):
    return type(kind, (), fields)()


class TestSpanMapping:
    def test_llm_span_recorded(self):
        h = ApproximatelySpanHandler("t")
        h.prepare_to_exit_span("s1", _span("LLMSpan", prompt="revenue?",
                                           completion="$42"))
        step = h.recorder.trace.steps[-1]
        assert step.tool == "llm" and step.result == "$42"
        assert step.args == {"prompt": "revenue?"}

    def test_retriever_query_agent_spans(self):
        h = ApproximatelySpanHandler("t")
        h.prepare_to_exit_span("s1", _span("QuerySpan", query_str="Q4 rev"))
        h.prepare_to_exit_span("s2", _span("RetrieverSpan",
                                           retrieval_str="10-k chunk"))
        h.prepare_to_exit_span("s3", _span("AgentRunSpan", agent_id="fin"))
        h.prepare_to_exit_span("s4", _span("SynthesisSpan"))
        kinds = [(s.kind, s.tool or "") for s in h.recorder.trace.steps]
        assert ("plan", "") in kinds
        assert ("tool_call", "retrieve") in kinds
        assert ("observation", "") in kinds

    def test_tool_call_span(self):
        h = ApproximatelySpanHandler("t")
        h.prepare_to_exit_span("s1", _span("ToolCallSpan",
                                           tool_name="sql", result="1 row"))
        step = h.recorder.trace.steps[-1]
        assert step.tool == "sql" and step.result == "1 row"

    def test_unknown_spans_ignored(self):
        h = ApproximatelySpanHandler("t")
        before = len(h.recorder.trace.steps)
        h.prepare_to_exit_span("s1", _span("SimpleSpan", label="x"))
        h.prepare_to_exit_span("s2", _span("EmbeddingSpan",
                                           model_name="ada"))
        h.prepare_to_exit_span("s3", None)
        h.prepare_to_exit_span("s4", "not a span")
        assert len(h.recorder.trace.steps) == before

    def test_drop_becomes_fail(self):
        h = ApproximatelySpanHandler("t")
        h.prepare_to_drop_span("s1", _span("LLMSpan"),
                               err=RuntimeError("429 again"))
        step = h.recorder.trace.steps[-1]
        assert step.kind == "error" and "429 again" in step.error

    def test_drop_without_error_uses_span_kind(self):
        h = ApproximatelySpanHandler("t")
        h.prepare_to_drop_span("s1", _span("RetrieverSpan"))
        assert "span dropped: RetrieverSpan" in \
            h.recorder.trace.steps[-1].error

    def test_hostile_span_never_raises(self):
        h = ApproximatelySpanHandler("t")

        class Bomb:
            def __getattr__(self, name):
                raise RuntimeError("boom")

        Bomb.__name__ = "LLMSpan"
        h.prepare_to_exit_span("s1", Bomb())  # must not raise
        h.prepare_to_drop_span("s2", Bomb(), err=Bomb())

    def test_open_span_bookkeeping(self):
        h = ApproximatelySpanHandler("t")
        h.new_span("s1", None, _span("LLMSpan"))
        h.new_span("s2", "s1", _span("SimpleSpan"))
        assert h._open == {"s1", "s2"}
        h.prepare_to_exit_span("s1", _span("LLMSpan", completion="x"))
        h.prepare_to_drop_span("s2", _span("SimpleSpan"))
        assert h._open == set()


class TestWireDispatcher:
    def test_add_method_shape(self):
        class FakeDispatcher:
            def __init__(self):
                self.added = []

            def add_span_handler(self, handler):
                self.added.append(handler)

        d = FakeDispatcher()
        h = ApproximatelySpanHandler("t")
        assert h.wire_dispatcher(d) is d
        assert d.added == [h]

    def test_handler_list_shape(self):
        class OldDispatcher:
            span_handlers: ClassVar[list] = []

        d = OldDispatcher()
        h = ApproximatelySpanHandler("t")
        h.wire_dispatcher(d)
        assert d.span_handlers == [h]

    def test_bad_object_raises(self):
        h = ApproximatelySpanHandler("t")
        with pytest.raises(RuntimeError):
            h.wire_dispatcher(object())

    def test_respond_and_report(self):
        h = ApproximatelySpanHandler("t")
        h.prepare_to_exit_span("s1", _span("LLMSpan", completion="ans"))
        h.respond()
        assert h.recorder.trace.steps[-1].kind == "response"
        assert h.report().trace_id == h.recorder.trace.id
