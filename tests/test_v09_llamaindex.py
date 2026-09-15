"""v0.9: LlamaIndex adapter — faked events, no llama_index dependency."""

from __future__ import annotations

import pytest

from approximately.contrib.llamaindex import ApproximatelyHandler


def _end(handler, name, payload=None):
    handler.on_event_end(name, payload or {}, "eid", "pid")


class TestEventMapping:
    def test_llm_end_recorded(self):
        h = ApproximatelyHandler("t")
        _end(h, "LLM", {"response": "42 apples"})
        step = h.recorder.trace.steps[-1]
        assert step.tool == "llm" and step.result == "42 apples"

    def test_llm_completion_fallback(self):
        h = ApproximatelyHandler("t")
        _end(h, "LLM", {"completion": "streamed answer"})
        assert h.recorder.trace.steps[-1].result == "streamed answer"

    def test_function_call_with_kwargs_dict(self):
        h = ApproximatelyHandler("t")
        _end(h, "FUNCTION_CALL", {
            "function_call": "sql_engine {'query': 'SELECT 1'}",
            "function_output": "1 row",
        })
        step = h.recorder.trace.steps[-1]
        assert step.tool == "sql_engine"
        assert step.args == {"query": "SELECT 1"}
        assert step.result == "1 row"

    def test_function_call_non_json_kwargs(self):
        h = ApproximatelyHandler("t")
        _end(h, "FUNCTION_CALL", {"function_call": "lookup (user-17)"})
        step = h.recorder.trace.steps[-1]
        assert step.tool == "lookup"
        assert step.args == {"input": "user-17"}

    def test_agent_step_and_retrieve(self):
        h = ApproximatelyHandler("t")
        _end(h, "AGENT_STEP", {"response": "planning join"})
        _end(h, "RETRIEVE", {"nodes": [1, 2, 3]})
        obs, ret = h.recorder.trace.steps[-2], h.recorder.trace.steps[-1]
        assert obs.kind == "observation" and "planning join" in obs.result
        assert ret.tool == "retrieve" and ret.result == "3 nodes"

    def test_exception_becomes_fail_step(self):
        h = ApproximatelyHandler("t")
        _end(h, "EXCEPTION", {"exception": "RateLimitError: 429"})
        step = h.recorder.trace.steps[-1]
        assert step.kind == "error" and "RateLimitError" in step.error

    def test_enum_event_type_via_name_attr(self):
        class FakeEventType:
            name = "LLM"

        h = ApproximatelyHandler("t")
        _end(h, FakeEventType(), {"response": "ok"})
        assert h.recorder.trace.steps[-1].tool == "llm"

    def test_unknown_and_hostile_events_ignored(self):
        h = ApproximatelyHandler("t")
        before = len(h.recorder.trace.steps)
        _end(h, "CHUNKING", {"whatever": 1})
        _end(h, 12345, None)  # weird type
        assert len(h.recorder.trace.steps) == before

    def test_hostile_payload_never_raises(self):
        h = ApproximatelyHandler("t")

        class Bomb:
            def keys(self):
                raise RuntimeError("boom")

        h.on_event_end("LLM", Bomb())  # must not raise
        h.on_event_end("LLM", {"response": Bomb()})  # preview swallows
        assert True


class TestWiring:
    def test_wire_into_manager_like_object(self):
        class FakeManager:
            def __init__(self):
                self.handlers = []

            def add_handler(self, handler):
                self.handlers.append(handler)

        mgr = FakeManager()
        h = ApproximatelyHandler("t")
        h.wire(mgr)
        assert mgr.handlers == [h]

    def test_wire_without_llamaindex_and_bad_object_raises(self):
        h = ApproximatelyHandler("t")
        with pytest.raises(RuntimeError):
            h.wire(object())  # neither manager nor Settings-like

    def test_respond_and_report(self):
        h = ApproximatelyHandler("t")
        _end(h, "LLM", {"response": "answer"})
        h.respond()
        assert h.recorder.trace.steps[-1].kind == "response"
        assert h.report().trace_id == h.recorder.trace.id

    def test_alias(self):
        from approximately.contrib.llamaindex import LlamaIndexCallbackHandler
        assert LlamaIndexCallbackHandler is ApproximatelyHandler
