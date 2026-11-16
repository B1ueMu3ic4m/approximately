"""v592: every numeric argument names its field on the wire.

The MCP tool handlers coerced numbers inline - ``int(args[...])``/
``float(args[...])`` - so a hostile or buggy client got the raw
conversion error ("invalid literal for int() with base 10: 'abc'",
no field name) when it got anything at all, and the worst case was
silent: ``limit: true`` passed ``int(True)`` and became limit=1.
The coercions route through _opt_int/_opt_float now: a wrong type
names its field ("limit must be an integer"), a bool is not a
number, a nan/inf float names itself, and the answer shape is the
same isError result every other refusal uses.
"""

import json

from approximately.mcp_server import ServerContext, handle_request
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _store(tmp_path):
    store = TraceStore(tmp_path / "s")
    rec = Recorder("arg audit", model="m/1", store=store, save=False)
    rec.tool("deploy", {"env": "x"}, result="ok")
    rec.respond("done", success=True)
    store.save(rec.trace)
    return store


def _call(tmp_path, tool, arguments):
    ctx = ServerContext(str(tmp_path / "s"))
    payload = handle_request({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": tool, "arguments": arguments},
    }, ctx)
    return payload["result"]


def test_a_string_limit_names_the_field(tmp_path):
    _store(tmp_path)
    result = _call(tmp_path, "list_traces", {"limit": "ten"})
    assert result["isError"]
    assert "limit must be an integer" in \
        result["content"][0]["text"], (
        "the raw 'invalid literal for int()' leak named no field")
    assert "Traceback" not in result["content"][0]["text"]


def test_a_bool_limit_is_not_a_number(tmp_path):
    _store(tmp_path)
    result = _call(tmp_path, "list_traces", {"limit": True})
    assert result["isError"], (
        "limit: true used to pass int(True) and become limit=1 "
        "silently")
    assert "limit must be an integer" in \
        result["content"][0]["text"]


def test_an_honest_integer_still_works(tmp_path):
    _store(tmp_path)
    result = _call(tmp_path, "list_traces", {"limit": 1})
    assert not result["isError"], "the honest client still served"
    rows = json.loads(result["content"][0]["text"])
    assert rows["traces"], "the truthful answer is unchanged"


def test_a_float_field_names_itself(tmp_path):
    _store(tmp_path)
    for tool, args in (("similar", {"trace_a": "x", "trace_b": "y",
                                    "min_score": "high"}),
                       ("find_duplicates",
                        {"threshold": float("nan")}),
                       ("find_duplicates",
                        {"threshold": float("inf")})):
        result = _call(tmp_path, tool, args)
        assert result["isError"], f"{args} must refuse"
        text = result["content"][0]["text"]
        assert "must be" in text, (
            f"{args} named no field: {text[:120]}")
        assert "Traceback" not in text


def test_an_int_float_is_a_refusal_not_a_round(tmp_path):
    _store(tmp_path)
    result = _call(tmp_path, "list_traces", {"limit": 2.5})
    assert result["isError"], \
        "2.5 silently rounded would be a different answer than asked"
    assert "limit must be an integer" in \
        result["content"][0]["text"]
