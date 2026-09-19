"""v0.63 — llamaindex adapter edges: span lifecycle, call parsing,
wire() without the framework."""

from __future__ import annotations

import pytest

from approximately.contrib.llamaindex import (
    ApproximatelyHandler,
    ApproximatelySpanHandler,
    _preview,
)


def test_span_lifecycle_records_and_drops():
    handler = ApproximatelySpanHandler("graph query")

    class RetrieverSpan:
        query_str = "flights to nrt"

    span = RetrieverSpan()
    handler.new_span(id="s1", span=span)
    handler.prepare_to_exit_span(id="s1", span=span)
    tools = [s.tool for s in handler.recorder.trace.steps]
    assert "retrieve" in tools

    class LLMSpan:
        prompt = "summarize"
        completion = "ok"

    dropped = LLMSpan()
    handler.new_span(id="s2", span=dropped)
    handler.prepare_to_drop_span(id="s2", span=dropped,
                                 err=RuntimeError("context overflow"))
    failures = [s for s in handler.recorder.trace.steps if s.error]
    assert failures, "dropped span recorded as failure"


def test_broken_span_never_breaks_the_query():
    handler = ApproximatelySpanHandler("hostile span")

    class Boom:
        def __getattr__(self, name):
            raise RuntimeError("boom")

    handler.new_span(id="s3", span=Boom())
    handler.prepare_to_exit_span(id="s3", span=Boom())  # swallow
    handler.prepare_to_drop_span(id="s3", span=Boom(), err=Boom())


def test_parse_call_dict_repr_and_freeform():
    handler = ApproximatelyHandler("parse edges")

    def _parse_call(raw):
        return handler._parse_call(raw)

    name, args = _parse_call('retriever {"query": "flights"}')
    assert name == "retriever" and args.get("query") == "flights"

    # no space: the whole string is the tool name, kwargs empty
    name, args = _parse_call("search(top_k=3)")
    assert name == "search(top_k=3)" and args == {}
    name, args = _parse_call("search {'top_k': 3}")
    assert name == "search"

    name, args = _parse_call("just a freeform string")
    assert name == "just"  # first token is the tool, rest stays raw

    name, args = _parse_call("")
    assert name == "function" and args == {}


def test_preview_flattens_and_truncates():
    assert _preview(None) == ""
    assert _preview("  spaced   out  ") == "spaced out"
    assert _preview({"a": 1}, limit=3) == '{"a'
    # non-JSON-serializable falls back to str() *inside* json.dumps,
    # so the string arrives quoted and the limit counts the quote
    assert _preview(BoomRepr(), limit=10) == '"boom repr'


class BoomRepr:
    def __repr__(self):
        return "boom repr!!"


def test_wire_without_llamaindex_raises_guidance(tmp_path, monkeypatch):
    handler = ApproximatelyHandler("no framework")

    class Managerless:
        pass

    import builtins

    real_import = builtins.__import__

    def guard(name, *a, **k):
        if name.startswith("llama_index"):
            raise ImportError("no llama_index")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", guard)
    with pytest.raises(RuntimeError, match="llama_index"):
        handler.wire(Managerless())


def test_wire_accepts_manager_directly():
    handler = ApproximatelyHandler("direct manager")

    class Manager:
        def __init__(self):
            self.callback_manager = None

        def add_handler(self, h):
            self.added = h

    manager = Manager()
    handler.wire(manager)
    assert manager.added is handler
