"""v328: the receiving end of the signed channel.

Fleet summaries, tail announcements and shift digests all travel
one way. ``webhook-serve`` is the zero-dependency other end: it
verifies ``X-Approximately-Signature`` against the same ``load_key``
every poster uses and archives what survives. A configured key
makes the server verify-only — an unauthenticated writer must not
be able to seed the ops log; with no key it archives rows marked
``verified: false`` and says so.
"""

import hashlib
import hmac
import json
import tempfile
from http.client import HTTPConnection
from pathlib import Path

from approximately.cli import cmd_webhook_serve
from approximately.receiver import serve
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _post(addr, body: bytes, signature=None):
    host, port = addr.split(":")
    conn = HTTPConnection(host, int(port), timeout=5)
    headers = {"Content-Type": "application/json"}
    if signature:
        headers["X-Approximately-Signature"] = signature
    conn.request("POST", "/", body=body, headers=headers)
    resp = conn.getresponse()
    data = json.loads(resp.read())
    status = resp.status
    conn.close()
    return status, data


def _signed(body: bytes, key: bytes) -> str:
    return "sha256=" + hmac.new(key, body, hashlib.sha256).hexdigest()


def _server(key=None):
    archive = Path(tempfile.mkdtemp()) / "webhook-log.jsonl"
    server, state = serve(archive, port=0, key=key)
    port = server.server_address[1]
    return server, state, archive, f"127.0.0.1:{port}"


def test_verified_post_is_archived():
    key = b"sekrit"
    server, _state, archive, addr = _server(key)
    try:
        body = json.dumps({"kind": "trace_failure", "task": "x"}).encode()
        status, resp = _post(addr, body, _signed(body, key))
        assert status == 200 and resp == {"received": True,
                                          "verified": True}
        rows = [json.loads(line) for line in
                archive.read_text(encoding="utf-8").splitlines()]
        assert len(rows) == 1
        assert rows[0]["verified"] is True
        assert rows[0]["kind"] == "trace_failure"
        assert rows[0]["payload"]["task"] == "x"
    finally:
        server.shutdown()


def test_bad_signature_gets_401_and_never_archives():
    key = b"sekrit"
    server, state, archive, addr = _server(key)
    try:
        body = b'{"kind": "trace_failure"}'
        status, resp = _post(addr, body, "sha256=" + "0" * 64)
        assert status == 401 and "error" in resp
        status, _ = _post(addr, body)  # absent signature
        assert status == 401
        assert not archive.exists(), "refused posts must not archive"
        assert state.refused == 2 and state.received == 0
    finally:
        server.shutdown()


def test_open_mode_archives_unverified_and_says_so():
    server, _state, archive, addr = _server()  # no key: open tap
    try:
        body = b'{"kind": "ops_digest"}'
        status, resp = _post(addr, body)
        assert status == 200 and resp["verified"] is False
        row = json.loads(archive.read_text(encoding="utf-8")
                         .splitlines()[0])
        assert row["verified"] is False
    finally:
        server.shutdown()


def test_health_endpoint():
    server, _state, _archive, addr = _server()
    try:

        host, port = addr.split(":")
        conn = HTTPConnection(host, int(port), timeout=5)
        conn.request("GET", "/health")
        resp = json.loads(conn.getresponse().read())
        conn.close()
        assert resp["ok"] is True and resp["verify_mode"] is False
    finally:
        server.shutdown()


def test_hostile_body_is_refused_not_fatal():
    key = b"sekrit"
    server, _state, _archive, addr = _server(key)
    try:
        body = b"not json at all"
        status, _resp = _post(addr, body, _signed(body, key))
        assert status == 400
        body = b'["a list, not an object"]'
        status, _ = _post(addr, body, _signed(body, key))
        assert status == 400
        # and the server still serves a good request afterwards
        good = b'{"kind": "spool"}'
        status, _resp = _post(addr, good, _signed(good, key))
        assert status == 200
    finally:
        server.shutdown()


def test_end_to_end_poster_to_receiver(tmp_path):
    """The loop, both ways: approximately posts a signed failure
    announcement; webhook-serve verifies and archives it."""
    from approximately.fleet import notify_webhook

    store = TraceStore(tmp_path / "s")
    with Recorder("the run that failed", store=store) as rec:
        rec.tool("sh", {}, agent="bot", result="x")
        rec.fail("boom")
    key = b"roundtrip"
    server, _state, archive, addr = _server(key)
    try:
        from approximately.tail import arrival_payload

        notify_webhook([], f"http://{addr}/",
                       signing_key=key,
                       payload=arrival_payload(store.list_traces()[0]))
        rows = [json.loads(line) for line in
                archive.read_text(encoding="utf-8").splitlines()]
        assert rows[0]["verified"] is True
        assert rows[0]["kind"] == "trace_failure"
    finally:
        server.shutdown()


def test_cli_door_parses_and_refuses_bad_port():
    import argparse

    args = argparse.Namespace(store=".", port=99999, key_file=None,
                              log=None)
    assert cmd_webhook_serve(args) == 2


def test_oversized_body_gets_413_before_the_read():
    from approximately.receiver import serve

    archive = Path(tempfile.mkdtemp()) / "log.jsonl"
    server, _state = serve(archive, port=0, key=None, max_bytes=64)
    try:
        host, port = server.server_address[:2]
        conn = HTTPConnection(host, int(port), timeout=5)
        big = b'{"kind": "' + b"x" * 200 + b'"}'
        conn.request("POST", "/", body=big,
                     headers={"Content-Length": str(len(big))})
        resp = conn.getresponse()
        data = json.loads(resp.read())
        status = resp.status
        conn.close()
        assert status == 413
        assert "exceeds" in data["error"]
        assert not archive.exists(), "refused bodies never archive"
        # and the receiver still serves normal traffic afterwards
        small = b'{"kind": "spool"}'
        status, _ = _post(f"{host}:{port}", small)
        assert status == 200
    finally:
        server.shutdown()
