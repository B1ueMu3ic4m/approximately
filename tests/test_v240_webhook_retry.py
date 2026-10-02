"""v240: the webhook retries like it means it.

A watcher that pages a human must survive a busy receiver: Slack
answers 503 under load, rate limiters answer 429, and a blip in
between is exactly when the alert matters most.  The old POST gave
up after one try on any HTTP error — including 503s the server
itself called transient.  Now: connection errors and 5xx/429 retry
with bounded exponential backoff (0.5s, 1s, 2s), a 429 honors a
capped Retry-After, and any other 4xx stays a definite answer (the
endpoint heard us; retrying just re-announces).  A fresh Request
per attempt, because urllib handlers may consume the payload.
"""

import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import ClassVar

import pytest

from approximately.fleet import notify_webhook


class _Scripted(BaseHTTPRequestHandler):
    """Pop responses off a script list; count every POST arrival."""

    responses: ClassVar[list] = []   # (status, headers) pairs
    arrivals: ClassVar[int] = 0

    def do_POST(self):
        type(self).arrivals += 1
        if not type(self).responses:
            self.send_response(200)
            self.end_headers()
            return
        status, headers = type(self).responses.pop(0)
        if status == 200:
            self.send_response(200)
            self.end_headers()
            return
        self.send_response(status)
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()

    def log_message(self, *args):
        pass


def _server(script):
    _Scripted.responses = list(script)
    _Scripted.arrivals = 0
    httpd = HTTPServer(("127.0.0.1", 0), _Scripted)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd, f"http://127.0.0.1:{httpd.server_port}"


def _post(url, **kw):
    return notify_webhook([], url, payload={"kind": "test"}, **kw)


def test_503_then_success_retries():
    httpd, url = _server([(503, None), (503, None), (200, None)])
    try:
        assert _post(url) == "200"
        assert _Scripted.arrivals == 3
    finally:
        httpd.shutdown()


def test_404_is_a_definite_answer():
    httpd, url = _server([(404, None)])
    try:
        assert _post(url) == "HTTP 404"
        assert _Scripted.arrivals == 1      # no retry on a plain 4xx
    finally:
        httpd.shutdown()


def test_429_honors_retry_after_then_succeeds():
    httpd, url = _server([(429, {"Retry-After": "0"}), (200, None)])
    started = time.monotonic()
    try:
        assert _post(url) == "200"
        assert _Scripted.arrivals == 2
        assert time.monotonic() - started < 1.0   # Retry-After: 0 is fast
    finally:
        httpd.shutdown()


def test_persistent_503_exhausts_and_raises():
    httpd, url = _server([(503, None)] * 10)
    try:
        with pytest.raises(RuntimeError, match="after 3 attempts"):
            _post(url)
        assert _Scripted.arrivals == 3
    finally:
        httpd.shutdown()


def test_attempts_is_honorable():
    httpd, url = _server([(503, None)] * 10)
    try:
        with pytest.raises(RuntimeError):
            _post(url, attempts=1)
        assert _Scripted.arrivals == 1
    finally:
        httpd.shutdown()


def test_retry_after_capped_at_five_seconds():
    from approximately.fleet import _retry_delay

    class _Fake:
        code = 429

        class headers:
            pass

    _Fake.headers.get = staticmethod(
        lambda name: "3600")                # a hostile Retry-After
    assert _retry_delay(_Fake(), 1) == 5.0
    _Fake.headers.get = staticmethod(lambda name: "garbage")
    assert _retry_delay(_Fake(), 1) == 0.5  # falls back to backoff


def test_retried_body_is_identical_bytes():
    # the HMAC over attempt 1 must cover the same body as attempt 2:
    # a re-serialized guess would break the receiver's signature
    seen = []

    class _Body(_Scripted):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            seen.append(self.rfile.read(length))
            type(self).arrivals += 1
            if len(seen) == 1:
                self.send_response(503)
            else:
                self.send_response(200)
            self.end_headers()

        def log_message(self, *args):
            pass

    _Body.responses = [(503, None), (200, None)]
    _Body.arrivals = 0
    httpd = HTTPServer(("127.0.0.1", 0), _Body)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        assert notify_webhook([], f"http://127.0.0.1:{httpd.server_port}",
                              payload={"kind": "test"}) == "200"
    finally:
        httpd.shutdown()
    assert len(seen) == 2 and seen[0] == seen[1]
