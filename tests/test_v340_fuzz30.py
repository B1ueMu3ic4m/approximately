"""Fuzz 30: hostile arguments at the MCP surface.

The surface is 50 tools wide now, and every handler takes a
JSON-decoded dict whose values could be anything a hostile or
buggy client sends: numbers where strings belong, negatives,
unicorns, a billion, unicode zero-widths, nested junk. The
contract under fuzz: the dispatch never raises out — every tool
answers with a result envelope whose payload is either data or an
error string, and the server stays alive for the next call.
"""

import tempfile

from approximately.mcp_server import _HANDLERS, _TOOLS, ServerContext
from approximately.store import TraceStore

HOSTILE_ARGS = [
    {},
    {"store": None},
    {"store": 123},
    {"store": ""},
    {"store": "/nonexistent/deeply/path"},
    {"store": "\u200b\u0000bad"},
    {"limit": "banana"},
    {"limit": -5},
    {"limit": 10 ** 18},
    {"keep_days": 0},
    {"keep_days": "7"},
    {"keep_days": 10 ** 12},
    {"since_days": -1},
    {"triage_top": None},
    {"grade_floor": 3},
    {"apply": "yes"},
    {"apply": True, "confirm": False},
    {"deep": {"a": {"b": {"c": [1, 2, {"d": None}]}}}},
    {"\u0000key": "value"},
    {"store": "." * 5000},
]


def test_every_tool_survives_every_hostile_argument_set():
    ctx = ServerContext(TraceStore(tempfile.mkdtemp()).directory)
    probed = 0
    for tool in _TOOLS:
        handler = _HANDLERS[tool["name"]]
        for args in HOSTILE_ARGS:
            try:
                payload = handler(ctx, dict(args))
            except (KeyError, ValueError, OSError):
                # the refusal idiom: the RPC layer turns these into
                # error envelopes - a word, never a crash. OSError
                # is the OS refusing a hostile path (too long, bad
                # syntax): environmental refusal, same class.
                pass
            except Exception as exc:  # anything else is a leak
                raise AssertionError(
                    f"{tool['name']} {list(args)}: leaked "
                    f"{type(exc).__name__}: {exc}") from exc
            else:
                assert isinstance(payload, dict), \
                    f"{tool['name']} {list(args)}: not a dict"
            probed += 1
    assert probed == len(_TOOLS) * len(HOSTILE_ARGS)


def test_rpc_layer_answers_hostile_calls_with_envelopes():
    ctx = ServerContext(TraceStore(tempfile.mkdtemp()).directory)
    calls = [
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
         "params": {"name": "retention",
                    "arguments": {"keep_days": "banana"}}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
         "params": {"name": "no_such_tool", "arguments": {}}},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
         "params": {"name": "inbox",
                    "arguments": {"limit": 10 ** 18}}},
        {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
         "params": None},
        {"jsonrpc": "2.0", "id": 5, "method": "no_such_method"},
    ]
    from approximately.mcp_server import handle_request

    for msg in calls:
        reply = handle_request(msg, ctx)
        assert (reply is not None and "result" in reply) or \
            "error" in reply, f"{msg['id']}: no envelope"
    # a hostile params=None must not crash the dispatcher
    reply = handle_request(calls[3], ctx)
    assert "error" in reply


def test_server_serves_after_the_fuzz():
    ctx = ServerContext(TraceStore(tempfile.mkdtemp()).directory)
    from approximately.mcp_server import handle_request

    for _ in range(5):
        for args in HOSTILE_ARGS:
            handle_request(
                {"jsonrpc": "2.0", "id": 9, "method": "tools/call",
                 "params": {"name": "inbox", "arguments": args}},
                ctx)
    reply = handle_request(
        {"jsonrpc": "2.0", "id": 10, "method": "tools/list"}, ctx)
    assert len(reply["result"]["tools"]) == 50, \
        "the surface is intact after the storm"


def test_every_declared_property_rejects_the_wrong_type():
    """Schema-aware sweep: each tool's declared properties get a
    value of the wrong type — a refusal or a dict, never a leak."""
    ctx = ServerContext(TraceStore(tempfile.mkdtemp()).directory)
    WRONG = {"string": 123, "number": "x", "boolean": "yes",
             "array": {}, "object": []}
    probed = 0
    for tool in _TOOLS:
        props = (tool.get("inputSchema") or {}).get("properties") \
            or {}
        handler = _HANDLERS[tool["name"]]
        for prop, spec in props.items():
            wrong = WRONG.get(spec.get("type"))
            if wrong is None:
                continue
            try:
                payload = handler(ctx, {prop: wrong})
            except (KeyError, ValueError, OSError):
                continue  # refusal, turned into an envelope
            except Exception as exc:
                raise AssertionError(
                    f"{tool['name']}.{prop}={wrong!r}: leaked "
                    f"{type(exc).__name__}: {exc}") from exc
            assert isinstance(payload, dict)
            probed += 1
    # 37-ish today: only typed properties are probed; the floor
    # catches a sweep that stops touching the surface entirely
    assert probed >= 30, f"schema sweep lost coverage: {probed}"
