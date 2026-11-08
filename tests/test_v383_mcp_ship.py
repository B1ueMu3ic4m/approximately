"""v383: the channel is agent-reachable.

`webhook-ship` was a shell door only — an agent with an MCP
client had no way to move evidence to another box. The
`webhook_ship` tool ships the same signed row through the same
`_ship_core` (one mechanics, two surfaces — the CLI's pins hold
byte-for-byte), signs with APPROXIMATELY_SIGNING_KEY at the
tool boundary, and the scoped probe comes back as data:
{"delivered": true} is the machine-checkable form of "1 row(s)
matched this trace". 51 tools.
"""

import json
import tempfile
from pathlib import Path

import pytest

from approximately.mcp_server import ServerContext, _tool_webhook_ship
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _sender_store():
    store = TraceStore(tempfile.mkdtemp())
    rec = Recorder("agent-shipped task", store=store)
    rec.tool("sh", {"cmd": "deploy"}, result="ok")
    rec.respond("done", success=True)
    store.save(rec.trace)
    return store, rec.trace


def _receiver(key=b"mcp-ship"):
    from approximately.receiver import serve

    archive = Path(tempfile.mkdtemp()) / "webhook-log.jsonl"
    server, _state = serve(archive, key=key, port=0)
    port = server.server_address[1]
    return server, archive, f"http://127.0.0.1:{port}"


def _ship(store, url, trace="latest", monkeypatch=None,
          monkeypatch_key=b"mcp-ship"):
    from approximately import integrity

    if monkeypatch is not None:
        monkeypatch.setattr(integrity, "load_key",
                            lambda f: monkeypatch_key)
    ctx = ServerContext(store.directory)
    return _tool_webhook_ship(ctx, {"url": url, "trace": trace})


def test_the_tool_ships_and_proves_delivery(monkeypatch):
    server, archive, url = _receiver()
    store, trace = _sender_store()
    try:
        result = _ship(store, url, trace.id, monkeypatch)
        assert result["trace_id"] == trace.id
        assert result["steps"] == 2
        assert result["status"] == "200"
        assert result["delivered"] is True, \
            "the scoped probe saw this trace's row"
        assert result["probe"]["rows"] == 1
        assert result["probe"]["verified"] == 1
        rows = [json.loads(line) for line in
                archive.read_text().splitlines()]
        assert rows[0]["payload"]["trace"]["task"] == \
            "agent-shipped task"
    finally:
        server.shutdown()


def test_latest_ships_the_newest_recording(monkeypatch):
    server, archive, url = _receiver()
    store = TraceStore(tempfile.mkdtemp())
    ids = []
    for i in range(2):
        rec = Recorder(f"agent task {i}", store=store)
        rec.tool("sh", {"cmd": "x"}, result="ok")
        rec.respond("done", success=True)
        store.save(rec.trace)
        ids.append(rec.trace.id)
    try:
        result = _ship(store, url, "latest", monkeypatch)
        assert result["trace_id"] == ids[-1], \
            "'latest' resolves like every other door"
    finally:
        server.shutdown()


def test_no_signing_key_is_a_refusal_not_a_silent_post(monkeypatch):
    server, _archive, url = _receiver()
    store, _trace = _sender_store()
    try:
        with pytest.raises(ValueError, match="without a signature"):
            _ship(store, url, monkeypatch_key=None)
    finally:
        server.shutdown()


def test_hostile_args_are_refused_at_the_boundary(monkeypatch):
    server, _archive, url = _receiver()
    store, _trace = _sender_store()
    try:
        with pytest.raises(ValueError, match="must be a string"):
            _ship(store, 123, monkeypatch=monkeypatch)
        with pytest.raises(ValueError, match="url is required"):
            _ship(store, None, monkeypatch=monkeypatch)
        with pytest.raises(ValueError, match="no trace found"):
            _ship(store, url, trace="nope", monkeypatch=monkeypatch)
    finally:
        server.shutdown()
