"""v0.8: AutoGen adapter — both seams, tested against fakes (no autogen)."""

from __future__ import annotations

import dataclasses
import logging
from typing import ClassVar

import pytest

from approximately.contrib.autogen import (
    AutoGenEventHandler,
    RecordingChatCompletionClient,
    record_autogen,
)
from approximately.recorder import Recorder

# -- fake autogen_core.events --------------------------------------------------

@dataclasses.dataclass
class LLMCallEvent:
    messages: list
    prompt_tokens: int = 0
    completion_tokens: int = 0
    response: object = None
    agent_id: str = "agent-1"


@dataclasses.dataclass
class FunctionCallEvent:
    agent_id: str = "agent-1"
    function: str = "search"
    content: str = '{"q": "mast"}'


@dataclasses.dataclass
class FunctionExecutionEvent:
    agent_id: str = "agent-1"
    function: str = "search"
    content: str = "3 hits"


@dataclasses.dataclass
class SelectSpeakerEvent:
    agent_id: str = "group"
    speakers: list = dataclasses.field(default_factory=lambda: ["planner"])


@dataclasses.dataclass
class TerminationEvent:
    agent_id: str = "runtime"
    content: str = "MaxMessageTermination"


@dataclasses.dataclass
class UnknownFutureEvent:  # emitted by a newer autogen we don't know
    content: str = "something new"


def _handler(rec):
    return AutoGenEventHandler(rec)


class TestEventHandler:
    def test_llm_call_recorded(self):
        rec = Recorder("t", save=False)
        _handler(rec).emit(logging.LogRecord(
            "autogen_core.events", logging.INFO, "p", 1,
            LLMCallEvent(messages=["hi"], completion_tokens=17,
                         response="hello"), None, None))
        step = rec.trace.steps[-1]
        assert step.tool == "llm"
        assert step.result == "hello"
        assert step.meta.get("tokens") == 17

    def test_function_call_and_execution(self):
        rec = Recorder("t", save=False)
        h = _handler(rec)
        h.emit(logging.LogRecord("e", 20, "p", 1,
                                 FunctionCallEvent(), None, None))
        h.emit(logging.LogRecord("e", 20, "p", 1,
                                 FunctionExecutionEvent(), None, None))
        call, executed = rec.trace.steps[-2], rec.trace.steps[-1]
        assert call.tool == "search" and call.kind == "tool_call"
        assert executed.kind == "observation"
        assert "result of search: 3 hits" in (executed.result or "")

    def test_speaker_and_termination(self):
        rec = Recorder("t", save=False)
        h = _handler(rec)
        h.emit(logging.LogRecord("e", 20, "p", 1,
                                 SelectSpeakerEvent(), None, None))
        h.emit(logging.LogRecord("e", 20, "p", 1,
                                 TerminationEvent(), None, None))
        texts = [s.result or "" for s in rec.trace.steps]
        assert any("select speaker: planner" in t for t in texts)
        assert any("termination: MaxMessageTermination" in t for t in texts)

    def test_unknown_events_ignored(self):
        rec = Recorder("t", save=False)
        h = _handler(rec)
        before = len(rec.trace.steps)
        h.emit(logging.LogRecord("e", 20, "p", 1,
                                 UnknownFutureEvent(), None, None))
        h.emit(logging.LogRecord("e", 20, "p", 1, "plain string", None, None))
        h.emit(logging.LogRecord("e", 20, "p", 1, None, None, None))
        assert len(rec.trace.steps) == before
        assert h.recorded == 0

    def test_exception_in_recording_never_propagates(self):
        rec = Recorder("t", save=False)
        h = _handler(rec)

        class Bomb:  # shape of an LLMCallEvent, completion_tokens explodes
            messages: tuple = ("hi",)
            response = None

            @property
            def completion_tokens(self):
                raise RuntimeError("boom")

        Bomb.__name__ = "LLMCallEvent"
        h.emit(logging.LogRecord("e", 20, "p", 1, Bomb(), None, None))
        # must not raise; the poisoned event is simply skipped
        assert h.recorded == 0


class TestRecordAutogenContext:
    def test_attach_detach(self):
        logger = logging.getLogger("autogen_core.events")
        assert not any(isinstance(h, AutoGenEventHandler)
                       for h in logger.handlers)
        with record_autogen("triage") as ctx:
            handlers = [h for h in logger.handlers
                        if isinstance(h, AutoGenEventHandler)]
            assert len(handlers) == 1
            ctx.handler.emit(logging.LogRecord(
                "e", 20, "p", 1, FunctionCallEvent(), None, None))
        assert not any(isinstance(h, AutoGenEventHandler)
                       for h in logger.handlers)
        assert any(s.tool == "search" for s in ctx.recorder.trace.steps)

    def test_detach_even_on_error(self):
        with pytest.raises(ValueError), record_autogen("t"):
            raise ValueError("agent blew up")
        logger = logging.getLogger("autogen_core.events")
        assert not any(isinstance(h, AutoGenEventHandler)
                       for h in logger.handlers)


# -- fake model client ---------------------------------------------------------

class FakeCreateResult:
    def __init__(self, content, finish_reason="stop", completion_tokens=5):
        self.content = content
        self.finish_reason = finish_reason

        class Usage:
            pass

        self.usage = Usage()
        self.usage.completion_tokens = completion_tokens


class FakeClient:
    model_info: ClassVar[dict] = {"family": "gpt-4o", "function_calling": True}
    calls = 0

    def create(self, messages=None, **kwargs):
        self.calls += 1
        return FakeCreateResult("final answer")

    def create_stream(self, **kwargs):
        return iter(["chunk1", "chunk2"])

    def count_tokens(self, text, **kw):
        return len(text)


class TestRecordingClient:
    def test_create_recorded_and_passthrough(self):
        inner = FakeClient()
        rec = Recorder("t", save=False)
        client = RecordingChatCompletionClient(inner, rec)
        result = client.create([{"role": "user", "content": "hi"}])
        assert result.content == "final answer"
        assert inner.calls == 1
        step = rec.trace.steps[-1]
        assert step.tool == "llm"
        assert "gpt-4o" in str(step.args)
        assert step.result == "final answer"

    def test_attribute_delegation(self):
        client = RecordingChatCompletionClient(FakeClient(), Recorder("t"))
        assert client.count_tokens("abcd") == 4
        assert client.model_info["family"] == "gpt-4o"

    def test_create_stream_passthrough_unrecorded(self):
        rec = Recorder("t", save=False)
        client = RecordingChatCompletionClient(FakeClient(), rec)
        assert list(client.create_stream()) == ["chunk1", "chunk2"]
        assert not any(s.tool == "llm" for s in rec.trace.steps)

    def test_recording_failure_does_not_break_inference(self):
        class BadRecorder:
            trace = None

            def tool(self, *a, **kw):
                raise RuntimeError("recorder exploded")

        client = RecordingChatCompletionClient(FakeClient(), BadRecorder())
        result = client.create([])
        assert result.content == "final answer"  # inference survived

    def test_respond_and_report(self):
        client = RecordingChatCompletionClient(FakeClient())
        client.create([])
        client.respond()
        assert client.recorder.trace.steps[-1].kind == "response"
        report = client.report()
        assert report.trace_id == client.recorder.trace.id
