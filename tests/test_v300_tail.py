"""v300: the tail — one line per arrival, a scream per failure.

``fleet --watch`` watches digest metrics; ``tail`` watches arrivals.
A pass sees what landed since the last one; failed arrivals render
as ALERT lines and (with a URL) ride the fleet's HMAC-signed webhook
channel — and a webhook failure never kills the watch. ``--once``
is the cron-able shape; ``--json`` is a one-pass payload.
"""

import json
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

from approximately.cli import cmd_tail
from approximately.fleet import notify_webhook
from approximately.mcp_server import ServerContext, _tool_tail
from approximately.store import TraceStore
from approximately.tail import arrival_payload, render_arrival, scan_pass, tail
from approximately.trace import Step, Trace


class _Hook(BaseHTTPRequestHandler):
    body = None
    status = 200

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        type(self).body = self.rfile.read(length)
        self.send_response(type(self).status)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *args):
        pass


def _server():
    srv = HTTPServer(("127.0.0.1", 0), _Hook)
    threading.Thread(target=srv.serve_forever,
                     daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_port}/hook"


def _save(store, task, success, tokens=0):
    t = Trace(task=task, model="m")
    t.add(Step(kind="tool_call", tool="sh", result="x",
               tokens=tokens))
    t.success = success
    store.save(t)
    return t


def test_scan_pass_sees_only_new():
    store = TraceStore(tempfile.mkdtemp())
    _save(store, "first", True)
    seen = set()
    first = scan_pass(store, seen)
    assert [t.task for t in first] == ["first"]
    second = scan_pass(store, seen)
    assert second == []
    _save(store, "second", False)
    third = scan_pass(store, seen)
    assert [t.task for t in third] == ["second"]
    assert seen == {t.id for t in store.list_traces()}


def test_render_arrival_flags():
    store = TraceStore(tempfile.mkdtemp())
    ok = _save(store, "fine", True, tokens=120)
    bad = _save(store, "broken", False)
    assert render_arrival(ok, alert=False).startswith("  ok  ")
    assert render_arrival(bad, alert=False).startswith("!! FAIL")
    assert render_arrival(bad, alert=True).startswith(">> ALERT")
    long = _save(store, "x" * 90, True)
    line = render_arrival(long, alert=False)
    assert line.endswith("...")
    assert "120tok" in render_arrival(ok, alert=False)


def test_tail_announces_failures_and_survives_webhook_errors():
    store = TraceStore(tempfile.mkdtemp())
    _save(store, "pre-existing", True)
    srv, url = _server()
    try:
        _Hook.status = 200

        def later():
            time.sleep(0.25)
            _save(store, "fresh failure", False, tokens=99)

        threading.Thread(target=later, daemon=True).start()
        lines = tail(store, once=False, interval=0.1, max_passes=6,
                     announce_failure_url=url,
                     announce_hook=notify_webhook)
        assert any(">> ALERT" in line for line in lines)
        assert any("webhook: 200" in line for line in lines)
        body = json.loads(_Hook.body)
        assert body["kind"] == "trace_failure"
        assert body["trace"]["tokens"] == 99

        # a 500-ing webhook must not kill the watch (retries are
        # exhausted with bounded backoff, then the tail logs and
        # moves on; the arrival must land DURING the watch)
        _Hook.status = 500

        def later2():
            time.sleep(0.25)
            _save(store, "second failure", False)

        threading.Thread(target=later2, daemon=True).start()
        lines = tail(store, once=False, interval=0.1, max_passes=6,
                     announce_failure_url=url,
                     announce_hook=notify_webhook)
        assert any("webhook failed" in line for line in lines)
        assert any("second failure" in line for line in lines)
    finally:
        srv.shutdown()


def test_arrival_payload_shape():
    store = TraceStore(tempfile.mkdtemp())
    t = _save(store, "the task", False, tokens=7)
    payload = arrival_payload(t)
    assert payload["kind"] == "trace_failure"
    assert payload["trace"]["id"] == t.id
    assert payload["trace"]["steps"] == 1
    assert "announced_at" in payload


def test_cli_once_and_json(tmp_path, capsys):
    store = TraceStore(tmp_path)
    _save(store, "one", True)
    import argparse

    args = argparse.Namespace(store=str(tmp_path), interval=0.1,
                              once=True, max_passes=None,
                              webhook=None, **{"json": True})
    assert cmd_tail(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["existing"] == 1
    assert payload["arrivals"][0]["trace"]["task"] == "one"
    # --json without --once is refused
    args = argparse.Namespace(store=str(tmp_path), interval=0.1,
                              once=False, max_passes=None,
                              webhook=None, **{"json": True})
    assert cmd_tail(args) == 2
    capsys.readouterr()


def test_cli_webhook_scheme_gate(tmp_path, capsys):
    import argparse

    args = argparse.Namespace(store=str(tmp_path), interval=0.1,
                              once=True, max_passes=None,
                              webhook="file:///tmp/x",
                              **{"json": False})
    assert cmd_tail(args) == 2
    capsys.readouterr()


def test_cli_streaming_max_passes(tmp_path, capsys):
    import argparse

    store = TraceStore(tmp_path)
    _save(store, "there", True)
    args = argparse.Namespace(store=str(tmp_path), interval=0.05,
                              once=False, max_passes=1,
                              webhook=None, **{"json": False})
    assert cmd_tail(args) == 0
    out = capsys.readouterr().out
    assert "already on file" in out


def test_mcp_tail_snapshot(tmp_path):
    store = TraceStore(tmp_path)
    for i in range(3):
        _save(store, f"run {i}", i == 2)
    payload = _tool_tail(ServerContext(str(tmp_path)), {})
    assert payload["total"] == 3
    assert [a["trace"]["task"] for a in payload["arrivals"]] == \
        ["run 2", "run 1", "run 0"]  # newest first
    flagged = payload["arrivals"][0]
    assert flagged["kind"] == "trace_failure"
    capped = _tool_tail(ServerContext(str(tmp_path)), {"limit": 1})
    assert len(capped["arrivals"]) == 1
