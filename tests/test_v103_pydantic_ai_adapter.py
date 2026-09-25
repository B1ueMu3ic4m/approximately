"""v103: pydantic-ai adapter — post-hoc message transcription.

Pydantic AI runs end with ``result.all_messages()``; the adapter turns
that history into an approximately trace without importing the
framework (pure duck-typing over part class names), so the tests use
fake message objects — the contrib CI job covers the real package.

Also pins the new- and old-era Usage naming (input/output vs
request/response tokens) and the unknown-part skip contract.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from approximately.contrib.pydantic_ai import (
    record_pydantic_result,
    trace_from_pydantic_ai,
)


@dataclass
class FakeUsage:
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class FakeOldUsage:
    request_tokens: int = 0
    response_tokens: int = 0


def _part(kind, content=None, tool_name="", args=None):
    """A part whose class NAME matches pydantic-ai's — the adapter
    dispatches on ``type(part).__name__`` (duck-typing by design)."""
    def _init(self, content=None, tool_name="", args=None):
        self.content = content
        self.tool_name = tool_name
        self.args = args
    cls = type(kind, (object,), {"__init__": _init})
    return cls(content=content, tool_name=tool_name, args=args)


@dataclass
class FakeMessage:
    kind: str
    parts: list = field(default_factory=list)
    usage: object = None


def _messages(new_usage=True):
    usage = (FakeUsage(input_tokens=40, output_tokens=10) if new_usage
             else FakeOldUsage(request_tokens=40, response_tokens=10))
    return [
        FakeMessage("ModelRequest", [
            _part("UserPromptPart", content="book the flight"),
        ]),
        FakeMessage("ModelResponse", [
            _part("ToolCallPart", tool_name="search_flights",
                  args={"route": "SFO-NRT"}),
        ], usage=usage),
        FakeMessage("ModelRequest", [
            _part("ToolReturnPart", tool_name="search_flights",
                  content={"price": 880}),
        ], usage=usage),
        FakeMessage("ModelResponse", [
            _part("TextPart", content="Booked JT-044 for $880"),
        ], usage=usage),
    ]


def test_transcription_shape():
    trace = trace_from_pydantic_ai(_messages(), task="book the flight")
    assert trace.task == "book the flight"
    kinds = [s.kind for s in trace.steps]
    assert kinds == ["plan", "tool_call", "tool_call", "response"]
    tool = trace.steps[1]
    assert tool.tool == "search_flights"
    assert tool.args == {"route": "SFO-NRT"}
    ret = trace.steps[2]
    assert "price" in ret.result
    assert ret.tokens == 50  # 40 in + 10 out
    assert trace.success is True
    assert trace.final_output == "Booked JT-044 for $880"


def test_old_usage_naming():
    trace = trace_from_pydantic_ai(_messages(new_usage=False))
    assert trace.steps[2].tokens == 50


def test_unknown_parts_skipped():
    msgs = [
        FakeMessage("ModelRequest", [
            _part("UserPromptPart", content="go"),
            _part("FuturePart", content="?"),
        ]),
        FakeMessage("ModelResponse", [
            _part("TextPart", content="done"),
        ]),
    ]
    trace = trace_from_pydantic_ai(msgs)
    kinds = [s.kind for s in trace.steps]
    assert "plan" in kinds and "response" in kinds
    assert len(trace.steps) == 2


def test_non_dict_args_previewed():
    msgs = [FakeMessage("ModelResponse", [
        _part("ToolCallPart", tool_name="x", args="raw string args"),
    ])]
    trace = trace_from_pydantic_ai(msgs)
    assert trace.steps[0].args == {"args": "raw string args"}


def test_record_pydantic_result_saves(tmp_path):
    from approximately.store import TraceStore

    store = TraceStore(str(tmp_path / "s"))

    class FakeResult:
        output = "Booked JT-044 for $880"

        def all_messages(self):
            return _messages()

    trace = record_pydantic_result("book the flight", FakeResult(),
                                   store=store)
    assert trace.final_output == "Booked JT-044 for $880"
    assert store.load(trace.id) is not None


def test_record_without_store_does_not_save(tmp_path):
    from approximately.store import TraceStore

    empty = TraceStore(str(tmp_path / "e"))

    class FakeResult:
        output = "ok"

        def all_messages(self):
            return _messages()

    record_pydantic_result("task", FakeResult())
    assert empty.list_traces() == []
