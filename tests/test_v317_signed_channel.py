"""v317: the signed batch — the channel promise kept.

``tail --webhook``'s help promised HMAC signing "when
APPROXIMATELY_SIGNING_KEY is set"; nothing read the variable — the
announcement travelled unsigned. This batch keeps the promise
(the same ``load_key`` every other poster uses), gives ``digest
--post`` the same signed channel, and teaches the digest to count
the postmortems a shift still owes (failed, unannotated).
"""

import argparse
import hashlib
import hmac
import json
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

from approximately.cli import cmd_digest, cmd_tail
from approximately.digest import build_digest, render_markdown
from approximately.mcp_server import ServerContext, _tool_digest
from approximately.store import TraceStore
from approximately.trace import Step, Trace


class _Capture(BaseHTTPRequestHandler):
    body = None
    headers = None
    status = 200

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        type(self).body = self.rfile.read(length)
        type(self).headers = dict(self.headers)
        self.send_response(type(self).status)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *args):
        pass


def _server():
    # class-level capture state must not leak between tests: a
    # slow runner that outruns the race would otherwise assert on
    # the previous test's request
    _Capture.body = None
    _Capture.headers = None
    srv = HTTPServer(("127.0.0.1", 0), _Capture)
    threading.Thread(target=srv.serve_forever,
                     daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_port}/hook"


def _save(store, task, success, tokens=10):
    t = Trace(task=task, model="m")
    t.add(Step(kind="tool_call", tool="sh", result="x",
               tokens=tokens))
    t.success = success
    store.save(t)
    return t


def test_tail_announces_signed_when_key_is_set(monkeypatch):
    monkeypatch.setenv("APPROXIMATELY_SIGNING_KEY", "sekrit")
    store = TraceStore(tempfile.mkdtemp())
    _save(store, "marker", True)  # the seen-set needs a baseline

    def later():
        time.sleep(0.3)
        _save(store, "doomed run", False)

    srv, url = _server()
    try:
        threading.Thread(target=later, daemon=True).start()
        args = argparse.Namespace(store=store.directory,
                                  webhook=url, once=False,
                                  json=False, interval=0.15,
                                  max_passes=12)
        assert cmd_tail(args) == 0
        body = _Capture.body
        assert body is not None, "the announcement never landed"
        expected = "sha256=" + hmac.new(
            b"sekrit", body, hashlib.sha256).hexdigest()
        assert _Capture.headers.get(
            "X-Approximately-Signature") == expected
    finally:
        srv.shutdown()


def test_tail_announces_unsigned_without_key(monkeypatch):
    monkeypatch.delenv("APPROXIMATELY_SIGNING_KEY", raising=False)
    store = TraceStore(tempfile.mkdtemp())
    _save(store, "marker", True)

    def later():
        time.sleep(0.3)
        _save(store, "doomed run", False)

    srv, url = _server()
    try:
        threading.Thread(target=later, daemon=True).start()
        args = argparse.Namespace(store=store.directory,
                                  webhook=url, once=False,
                                  json=False, interval=0.15,
                                  max_passes=12)
        assert cmd_tail(args) == 0
        assert _Capture.body is not None
        assert "X-Approximately-Signature" not in _Capture.headers
    finally:
        srv.shutdown()


def _store_with_owes():
    store = TraceStore(tempfile.mkdtemp())
    _save(store, "owed one", False)
    _save(store, "owed two", False)
    noted = _save(store, "annotated failure", False)
    store.annotate(noted.id, "postmortemed")
    _save(store, "fine", True)
    return store


def test_briefs_due_counts_unannotated_failures():
    payload = build_digest(_store_with_owes())
    assert payload["briefs_due"] == 2
    page = render_markdown(payload)
    assert "postmortems owed: 2" in page


def test_mcp_digest_carries_briefs_due():
    store = _store_with_owes()
    payload = _tool_digest(ServerContext(store.directory), {})
    assert payload["briefs_due"] == 2


def test_digest_post_delivers_signed_markdown(monkeypatch,
                                              capsys):
    monkeypatch.setenv("APPROXIMATELY_SIGNING_KEY", "sekrit")
    store = _store_with_owes()
    srv, url = _server()
    try:
        args = argparse.Namespace(store=store.directory,
                                  digest_dir=None, triage_top=5,
                                  grade_floor=None, json=False,
                                  out=None, post=url)
        assert cmd_digest(args) == 0
        assert "posted: HTTP 200" in capsys.readouterr().out
        body = json.loads(_Capture.body)
        assert body["kind"] == "ops_digest"
        assert "# ops digest" in body["markdown"]
        expected = "sha256=" + hmac.new(
            b"sekrit", _Capture.body, hashlib.sha256).hexdigest()
        assert _Capture.headers.get(
            "X-Approximately-Signature") == expected
    finally:
        srv.shutdown()


def test_digest_post_refuses_json_and_reports_failure(capsys):
    store = _store_with_owes()
    args = argparse.Namespace(store=store.directory,
                              digest_dir=None, triage_top=5,
                              grade_floor=None, json=True,
                              out=None, post="http://x/hook")
    assert cmd_digest(args) == 2
    assert "--json" in capsys.readouterr().err
    args.json = False
    args.post = "http://127.0.0.1:9/hook"  # nothing listens there
    assert cmd_digest(args) == 1
    assert "delivery failed" in capsys.readouterr().err
