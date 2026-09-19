"""v0.61 — adapter dispatch paths without the frameworks installed.

crewai/langgraph/agents_sdk adapters are defensive against framework
version drift; a fake events/bus/handler surface exercises the real
dispatch logic locally (the contrib CI job covers the real packages).
"""

from __future__ import annotations

import json
import sys
import types

from approximately.contrib.agents_sdk import AgentsSDKProcessor
from approximately.contrib.crewai import CrewAIRecorder, _events_module
from approximately.contrib.langgraph import ApproximatelyCallbackHandler


# -- crewai -------------------------------------------------------------------

def _install_fake_crewai(monkeypatch):
    """Fake crewai_events with a bus that records registrations."""
    registered = []

    class FakeBus:
        @staticmethod
        def register_handler(event_type, handler):
            registered.append((event_type, handler))

    class ToolUsageFinished:
        pass

    class ToolUsageError:
        pass

    class CrewKickoffCompleted:
        pass

    fake = types.ModuleType("crewai_events")
    fake.crewai_event_bus = FakeBus
    fake.ToolUsageFinished = ToolUsageFinished
    fake.ToolUsageError = ToolUsageError
    fake.CrewKickoffCompleted = CrewKickoffCompleted
    monkeypatch.setitem(sys.modules, "crewai_events", fake)
    return registered


def test_events_module_finds_fake(monkeypatch):
    _install_fake_crewai(monkeypatch)
    events = _events_module()
    assert events is not None and hasattr(events, "crewai_event_bus")


def test_events_module_absent_returns_none(monkeypatch):
    monkeypatch.setitem(sys.modules, "crewai_events", None)
    import importlib

    monkeypatch.delitem(sys.modules, "crewai_events", raising=False)
    assert _events_module() is None


def test_crewai_register_and_event_dispatch(monkeypatch):
    registered = _install_fake_crewai(monkeypatch)
    rec = CrewAIRecorder("quarterly report crew")
    rec.register()
    assert registered, "handler registered on the fake bus"
    assert set(rec._handlers) == {"ToolUsageFinished", "ToolUsageError",
                                  "CrewKickoffCompleted"}

    handlers = [h for _, h in registered]
    tool_done = next(h for (et, _), h in zip(registered, handlers)
                     if et.__name__ == "ToolUsageFinished")
    tool_done(source=None, payload={"name": "web_search",
                                    "output": "3 results"})
    tool_err = next(h for (et, _), h in zip(registered, handlers)
                    if et.__name__ == "ToolUsageError")
    tool_err(source=None, payload={"name": "web_search",
                                   "error": "timeout"})
    kick = next(h for (et, _), h in zip(registered, handlers)
                if et.__name__ == "CrewKickoffCompleted")
    kick(source=None, payload=None)

    steps = rec.recorder.trace.steps
    assert steps[0].tool == "web_search" and "3 results" in steps[0].result
    assert steps[1].error == "timeout"
    # CrewKickoffCompleted deliberately records nothing: outcome is
    # owned by the caller, who knows whether the task succeeded
    rec.recorder.respond("crew finished the report", success=True)
    assert rec.recorder.trace.steps[-1].kind == "response"


def test_crewai_without_bus_is_noop():
    rec = CrewAIRecorder("no events installed")
    rec.register()  # _events_module() -> None path
    assert rec._handlers == []


# -- langgraph ----------------------------------------------------------------

def test_langgraph_full_callback_cycle():
    handler = ApproximatelyCallbackHandler("book a flight")
    handler.on_chain_start(None, {"input": 1})
    handler.on_chat_model_start(None, [{"role": "user",
                                       "content": "hi"}], run_id="r1")
    handler.on_tool_start({"name": "search_flights"}, "{}", run_id="t1")
    handler.on_tool_end(["Flight 1", "Flight 2"], run_id="t1")
    handler.on_tool_start({"name": "book"}, "{}", run_id="t2")
    handler.on_tool_error(RuntimeError("sold out"), run_id="t2")
    handler.on_llm_error(ValueError("rate limit"))
    handler.on_chain_error(RuntimeError("chain blew up"))
    steps = handler.recorder.trace.steps
    kinds = [(s.tool, bool(s.error)) for s in steps]
    assert ("search_flights", False) in kinds
    assert ("book", True) in kinds
    assert ("llm", True) in kinds
    handler.respond("done", success=False)
    report = handler.report()
    assert report.trace_id == handler.recorder.trace.id


def test_langgraph_unknown_tool_and_depth_floor():
    handler = ApproximatelyCallbackHandler("edge cases")
    handler.on_tool_end("orphan output", run_id="unknown")  # no start
    handler.on_chain_end({})  # depth floor at 0
    handler.on_chain_end({})
    assert handler._chain_depth == 0
    assert handler.recorder.trace.steps[0].tool == "unknown_tool"


# -- agents_sdk ---------------------------------------------------------------

def test_agents_sdk_processor_span_dispatch():
    proc = AgentsSDKProcessor("research task")

    class Span:
        def __init__(self, **kw):
            self.__dict__.update(kw)

    class FunctionSpanData:
        def __init__(self):
            self.name = "web_search"
            self.input = json.dumps({"q": "x"})
            self.output = "results"

    class GenerationSpanData:
        model = "gpt-fake"
        output = "thinking..."
        usage = {"output_tokens": 17}

    proc.on_span_end(Span(span_id="s1", span_data=FunctionSpanData(),
                          error=None))
    proc.on_span_end(Span(span_id="s2", span_data=GenerationSpanData(),
                          error=None))
    proc.on_trace_start(Span(name="tenant-42 research"))
    assert proc.recorder.trace.task == "tenant-42 research"
    steps = proc.recorder.trace.steps
    assert "web_search" in [s.tool for s in steps]
    assert "llm" in [s.tool for s in steps]
    proc.respond()
    assert proc.recorder.trace.success is True
