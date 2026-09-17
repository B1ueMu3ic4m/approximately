"""Zero-dependency MCP (Model Context Protocol) stdio server.

Speaks JSON-RPC 2.0 over line-delimited stdio — the transport MCP
clients (Claude Desktop, Zed, IDEs) use — so an agent can call the
toolkit directly: list/query traces, attribute failures, verify
evidence, survey a fleet. Standard library only; no MCP SDK.

Protocol surface implemented: ``initialize``, ``notifications/
initialized``, ``ping``, ``tools/list``, ``tools/call``. Requests
longer than ``MAX_LINE`` bytes are rejected so a hostile client
cannot balloon memory; malformed JSON gets a -32700 error, unknown
methods -32601, bad params -32602.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

MAX_LINE = 1_000_000
PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "approximately", "version": "0.37.0"}

_TOOLS: List[Dict[str, Any]] = [
    {
        "name": "list_traces",
        "description": "List trace ids in a store with task, success "
                       "flag and step count.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "store": {"type": "string",
                          "description": "store directory (default: "
                                         "server's --store)"},
                "limit": {"type": "integer", "minimum": 1,
                          "maximum": 1000},
            },
        },
    },
    {
        "name": "attribute",
        "description": "Attribute a trace: primary MAST failure mode, "
                       "confidence, and per-detection evidence.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "trace": {"type": "string"},
                "store": {"type": "string"},
            },
            "required": ["trace"],
        },
    },
    {
        "name": "verify",
        "description": "Verify the HMAC evidence chain of a trace; "
                       "returns the verdict (intact, tampered, "
                       "wrong-key, unsigned, rolled-back).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "trace": {"type": "string"},
                "store": {"type": "string"},
            },
            "required": ["trace"],
        },
    },
    {
        "name": "survey",
        "description": "Fleet summary over one or more store "
                       "directories: trace counts, failure rates, "
                       "trend verdicts.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "stores": {"type": "array",
                           "items": {"type": "string"}},
            },
            "required": ["stores"],
        },
    },
    {
        "name": "query",
        "description": "Select traces with an expression, e.g. "
                       "\"success == false and mode == FM-2.1\".",
        "inputSchema": {
            "type": "object",
            "properties": {
                "expression": {"type": "string"},
                "store": {"type": "string"},
            },
            "required": ["expression"],
        },
    },
]


class ServerContext:
    """Default store binding shared by the tools."""

    def __init__(self, store: str):
        self.store = store


def _store(ctx: ServerContext, args: Dict[str, Any]):
    from .store import TraceStore

    return TraceStore(Path(args.get("store") or ctx.store))


def _tool_list_traces(ctx: ServerContext, args: Dict[str, Any]) -> dict:
    limit = int(args.get("limit", 100))
    traces = _store(ctx, args).list_traces()[:limit]
    return {"traces": [{"id": t.id, "task": t.task,
                        "success": t.success,
                        "steps": len(t.steps)} for t in traces]}


def _tool_attribute(ctx: ServerContext, args: Dict[str, Any]) -> dict:
    from .attributor import attribute

    store = _store(ctx, args)
    trace = store.load(str(args["trace"]))
    if trace is None:
        raise KeyError(f"no trace {args['trace']!r} in store")
    report = attribute(trace)
    return {
        "trace": trace.id,
        "failed": report.failed,
        "primary_mode": report.primary_mode.id,
        "label": report.category_label,
        "detections": [{"mode": d.mode_id,
                        "step": d.step_index,
                        "confidence": d.confidence,
                        "source": d.source,
                        "evidence": d.evidence}
                       for d in report.detections],
    }


def _tool_verify(ctx: ServerContext, args: Dict[str, Any]) -> dict:
    from .integrity import verify

    store = _store(ctx, args)
    trace = store.load(str(args["trace"]))
    if trace is None:
        raise KeyError(f"no trace {args['trace']!r} in store")
    result = verify(trace)
    return {"trace": trace.id, "verdict": result.verdict}


def _tool_survey(ctx: ServerContext, args: Dict[str, Any]) -> dict:
    from .fleet import survey, webhook_payload

    paths = [Path(p) for p in args["stores"]]
    return webhook_payload(survey(paths))


def _tool_query(ctx: ServerContext, args: Dict[str, Any]) -> dict:
    from .query import select

    found = select(_store(ctx, args).list_traces(),
                   str(args["expression"]))
    return {"count": len(found),
            "ids": [t.id for t in found]}


_HANDLERS = {
    "list_traces": _tool_list_traces,
    "attribute": _tool_attribute,
    "verify": _tool_verify,
    "survey": _tool_survey,
    "query": _tool_query,
}


def _error(request_id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": request_id,
            "error": {"code": code, "message": message}}


def handle_request(msg: Dict[str, Any], ctx: ServerContext) -> Optional[dict]:
    """One JSON-RPC request -> response dict, or None for
    notifications. Raises ValueError for malformed envelopes."""
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
        raise ValueError("not a JSON-RPC 2.0 message")
    method = str(msg.get("method"))
    request_id = msg.get("id")
    if request_id is None:
        return None  # notification: accepted, never answered
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": request_id,
                "result": {"protocolVersion": PROTOCOL_VERSION,
                           "capabilities": {"tools": {}},
                           "serverInfo": SERVER_INFO}}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": request_id, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": request_id,
                "result": {"tools": _TOOLS}}
    if method == "tools/call":
        return _tools_call(msg, ctx, request_id)
    return _error(request_id, -32601, f"unknown method {method!r}")


def _tools_call(msg: Dict[str, Any], ctx: ServerContext,
                request_id) -> dict:
    params: Dict[str, Any] = msg.get("params") or {}
    name = str(params.get("name") or "")
    handler = _HANDLERS.get(name)
    if handler is None:
        return _error(request_id, -32602, f"unknown tool {name!r}")
    tool_args = params.get("arguments") or {}
    try:
        payload = handler(ctx, tool_args)
    except KeyError as exc:
        payload = {"error": str(exc)}
    except Exception as exc:  # tool-level failure, still a result
        payload = {"error": f"{type(exc).__name__}: {exc}"}
    return {"jsonrpc": "2.0", "id": request_id,
            "result": {"content": [
                {"type": "text", "text": json.dumps(payload, indent=2,
                                                    default=str)}],
                "isError": "error" in payload}}


def serve(read, write, ctx: ServerContext,
          max_requests: Optional[int] = None) -> int:
    """Line-delimited loop over two byte/text streams. Returns the
    number of responses written. Malformed JSON lines produce a
    -32700 error but do not stop the server."""
    handled = 0
    while max_requests is None or handled < max_requests:
        try:
            line = read()
        except StopIteration:  # iterator-backed streams: clean EOF
            break
        if line is None or line == "":
            break
        response = _handle_line(line.strip(), ctx)
        if response is not None:
            write(json.dumps(response) + "\n")
            handled += 1
    return handled


def _handle_line(line: str, ctx: ServerContext) -> Optional[dict]:
    """One input line -> one response (None for notifications)."""
    if not line:
        return None
    if len(line) > MAX_LINE:
        return _error(None, -32600, "request too large")
    try:
        msg: Any = json.loads(line)
    except json.JSONDecodeError:
        return _error(None, -32700, "parse error")
    if not isinstance(msg, dict):
        return _error(None, -32600, "invalid request envelope")
    try:
        return handle_request(msg, ctx)
    except ValueError:
        return _error(msg.get("id"), -32600, "invalid request envelope")


def cmd_mcp(args) -> int:
    """CLI entry: serve MCP over real stdio."""
    ctx = ServerContext(args.store)
    stdin = getattr(args, "_stdin", sys.stdin)
    stdout = getattr(args, "_stdout", sys.stdout)
    served = serve(stdin.readline, stdout.write, ctx,
                   max_requests=getattr(args, "_max_requests", None))
    stdout.flush()
    if getattr(args, "_report", False):
        print(f"served {served} request(s)", file=sys.stderr)
    return 0
