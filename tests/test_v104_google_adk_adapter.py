"""v104: google-adk adapter — post-hoc event transcription.

A google-adk run is a list of Events; trace_from_adk_events turns
that history into an approximately trace without importing the
framework (duck-typing on part attributes: function_call /
function_response / text). Tests run on fake events; the contrib CI
job covers the real package.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from approximately.contrib.google_adk import (
    record_adk_events,
    trace_from_adk_events,
)


def _part(kind, **kw):
    def _init(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)
    cls = type(kind, (object,), {"__init__": _init})
    return cls(**kw)


@dataclass
class FakeContent:
    parts: list = field(default_factory=list)


@dataclass
class FakeEvent:
    author: str = "agent"
    content: object = None
    usage_metadata: object = None


def _events():
    return [
        FakeEvent(author="user", content=FakeContent([
            _part("Part", text="book the flight"),
        ])),
        FakeEvent(content=FakeContent([
            _part("Part", function_call=_part("FunctionCall",
                                              name="search_flights",
                                              args={"route": "SFO-NRT"})),
        ])),
        FakeEvent(usage_metadata=_part("Usage", prompt_token_count=40,
                                       candidates_token_count=10),
                  content=FakeContent([
            _part("Part", function_response=_part(
                "FunctionResponse", name="search_flights",
                response={"price": 880})),
        ])),
        FakeEvent(content=FakeContent([
            _part("Part", text="Booked JT-044 for $880"),
        ])),
    ]


def test_transcription_shape():
    trace = trace_from_adk_events(_events(), task="book the flight")
    assert trace.task == "book the flight"
    kinds = [s.kind for s in trace.steps]
    assert kinds == ["plan", "tool_call", "tool_call", "response"]
    call = trace.steps[1]
    assert call.tool == "search_flights"
    assert call.args == {"route": "SFO-NRT"}
    ret = trace.steps[2]
    assert "price" in ret.result
    assert ret.tokens == 50  # 40 prompt + 10 candidates
    assert trace.success is True
    assert trace.final_output == "Booked JT-044 for $880"


def test_control_events_skipped():
    trace = trace_from_adk_events([
        FakeEvent(content=None),                       # yield/transfer
        FakeEvent(content=FakeContent(parts=[])),      # empty parts
        *_events(),
    ])
    assert len(trace.steps) == 4


def test_non_dict_call_args_previewed():
    events = [FakeEvent(content=FakeContent([
        _part("Part", function_call=_part("FunctionCall", name="x",
                                          args="raw")),
    ]))]
    trace = trace_from_adk_events(events)
    assert trace.steps[0].args == {"args": "raw"}


def test_blank_text_skipped():
    events = [FakeEvent(author="user", content=FakeContent([
        _part("Part", text="   "),
    ]))]
    trace = trace_from_adk_events(events)
    assert trace.steps == []


def test_record_saves_and_defaults(tmp_path):
    from approximately.store import TraceStore

    store = TraceStore(str(tmp_path / "s"))
    trace = record_adk_events("book the flight", _events(), store=store)
    assert store.load(trace.id) is not None
    assert trace.final_output == "Booked JT-044 for $880"
