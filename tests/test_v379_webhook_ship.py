"""v379: the channel carries evidence, not just counts.

The signed channel moved alerts, screams, briefs and pings —
but never a trace. ``webhook-ship`` posts a recorded trace
(integrity block intact) to another box's receiver as a
``trace_ship`` row, and the scoped readback proves THIS trace
landed: a trace id matches only the row it rode in on, the
same nonce discipline the ping uses. The receiving box's store
is untouched — importing foreign evidence is its call, and
foreign evidence must not acquire OUR integrity chain.
"""

import argparse
import json
import tempfile
from pathlib import Path

from approximately.cli import cmd_webhook_ship
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _receiver(key=None):
    from approximately.receiver import serve

    archive = Path(tempfile.mkdtemp()) / "webhook-log.jsonl"
    server, _state = serve(archive, key=key, port=0)
    port = server.server_address[1]
    return server, archive, f"http://127.0.0.1:{port}"


def _store_with_trace():
    store = TraceStore(tempfile.mkdtemp())
    rec = Recorder("ship me", store=store)
    rec.tool("sh", {"cmd": "deploy"}, result="ok")
    rec.respond("done", success=True)
    store.save(rec.trace)
    return store, rec.trace


def _keyfile():
    path = Path(tempfile.mkdtemp()) / "key"
    path.write_bytes(b"ship-key")
    return str(path)


def _ship(store, url):
    args = argparse.Namespace(trace="latest", url=url,
                              key_file=_keyfile(),
                              store=str(store.directory))
    return cmd_webhook_ship(args)


def test_a_shipped_trace_lands_and_proves_itself(capsys):
    server, archive, url = _receiver(key=b"ship-key")
    store, trace = _store_with_trace()
    try:
        assert _ship(store, url) == 0
        out = capsys.readouterr().out
        assert f"shipped: HTTP 200 (trace {trace.id}, " in out
        assert ("receiver archive (scoped to this trace): "
                "1 row(s) matched this trace, 1 verified") in out
        rows = [json.loads(line) for line in
                archive.read_text().splitlines()]
        assert rows[0]["kind"] == "trace_ship"
        assert rows[0]["verified"] is True
        shipped = rows[0]["payload"]["trace"]
        assert shipped["task"] == "ship me"
        assert shipped["meta"]["integrity"], \
            "the trace rides with its own integrity block"
    finally:
        server.shutdown()


def test_ship_refuses_an_unknown_trace(capsys):
    server, _archive, url = _receiver(key=b"ship-key")
    store = TraceStore(tempfile.mkdtemp())
    try:
        args = argparse.Namespace(trace="nope", url=url,
                                  key_file=_keyfile(),
                                  store=str(store.directory))
        raised = False
        try:
            cmd_webhook_ship(args)
        except SystemExit as exc:
            raised = True
            assert "no trace found" in str(exc)
        assert raised
    finally:
        server.shutdown()


def test_ship_without_a_key_refuses(capsys, monkeypatch):
    server, _archive, url = _receiver(key=b"ship-key")
    store, _trace = _store_with_trace()
    try:
        args = argparse.Namespace(trace="latest", url=url,
                                  key_file=None,
                                  store=str(store.directory))
        from approximately import integrity

        monkeypatch.setattr(integrity, "load_key",
                            lambda f: None)
        assert cmd_webhook_ship(args) == 2
        assert "without a signature" in capsys.readouterr().err
    finally:
        server.shutdown()
