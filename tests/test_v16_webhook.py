"""v0.16: fleet webhooks — signed JSON alerts for worsening trends."""

from __future__ import annotations

import hashlib
import hmac
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import ClassVar

import pytest

from approximately.fleet import notify_webhook, survey, webhook_payload
from approximately.recorder import Recorder
from approximately.store import TraceStore


@pytest.fixture()
def populated(tmp_path):
    store = TraceStore(tmp_path / "s1")
    rec = Recorder("t", store=store, save=False)
    rec.tool("deploy", {}, result="ok")
    rec.respond("done", success=False)
    store.save(rec.trace)
    return survey([tmp_path / "s1"])


class _Capture(BaseHTTPRequestHandler):
    received: ClassVar[list] = []

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        _Capture.received.append({
            "body": body,
            "signature": self.headers.get("X-Approximately-Signature"),
            "content_type": self.headers.get("Content-Type"),
        })
        self.send_response(200)
        self.end_headers()

    def log_message(self, *args):
        pass


@pytest.fixture()
def server():
    httpd = HTTPServer(("127.0.0.1", 0), _Capture)
    _Capture.received = []
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_port}"
    httpd.shutdown()


class TestPayload:
    def test_shape(self, populated):
        payload = webhook_payload(populated)
        assert payload["worsening_stores"] == []
        store = payload["stores"][0]
        assert store["traces"] == 1
        assert store["failure_rate"] == 1.0
        assert store["trend_verdict"] in ("improving", "stable",
                                          "worsening")

    def test_worsening_listed(self, tmp_path):
        import time

        store = TraceStore(tmp_path / "bad")
        for i, (ok, age) in enumerate([(True, 30), (True, 30),
                                       (False, 10), (False, 3)]):
            rec = Recorder(f"t{i}", store=store, save=False)
            rec.tool("x", {}, result="r")
            rec.respond("done", success=ok)
            rec.trace.created_at = int(time.time() - age * 86400)
            store.save(rec.trace)
        payload = webhook_payload(survey([tmp_path / "bad"]))
        assert len(payload["worsening_stores"]) == 1


class TestDelivery:
    def test_unsigned_post(self, populated, server):
        status = notify_webhook(populated, server)
        assert status == "200"
        assert len(_Capture.received) == 1
        assert _Capture.received[0]["signature"] is None
        assert _Capture.received[0]["content_type"] == "application/json"
        body = json.loads(_Capture.received[0]["body"])
        assert "stores" in body

    def test_signed_post_verifiable(self, populated, server):
        key = b"webhook-secret" * 3
        status = notify_webhook(populated, server, signing_key=key)
        assert status == "200"
        sent = _Capture.received[0]
        expected = hmac.new(key, sent["body"], hashlib.sha256).hexdigest()
        assert sent["signature"] == f"sha256={expected}"

    def test_signature_covers_body(self, populated, server):
        key = b"k" * 8
        notify_webhook(populated, server, signing_key=key)
        body = _Capture.received[0]["body"]
        wrong = hmac.new(b"other-key", body, hashlib.sha256).hexdigest()
        sent_sig = _Capture.received[0]["signature"]
        assert sent_sig != f"sha256={wrong}"

    def test_bad_url_raises(self, populated):
        # unroutable address: connection attempt must surface as
        # RuntimeError, never as a silent success
        with pytest.raises(RuntimeError, match="delivery failed"):
            notify_webhook(populated, "http://10.255.255.1/nope",
                           timeout=1.0)

    def test_non_http_scheme_refused(self, populated, tmp_path):
        secret = tmp_path / "secrets.txt"
        secret.write_text("should never be sent anywhere")
        with pytest.raises(RuntimeError, match="must be http"):
            notify_webhook(populated, f"file://{secret}")

    def test_http_error_reported(self, populated, server):
        class Rejecting(BaseHTTPRequestHandler):
            def do_POST(self):
                self.send_response(500)
                self.end_headers()

            def log_message(self, *args):
                pass

        httpd = HTTPServer(("127.0.0.1", 0), Rejecting)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            status = notify_webhook(populated,
                                    f"http://127.0.0.1:{httpd.server_port}")
            assert status == "HTTP 500"
        finally:
            httpd.shutdown()


class TestCli:
    def test_fleet_webhook_flag(self, tmp_path, populated, server,
                                capsys):
        from approximately.cli import main

        store_dir = tmp_path / "s1"
        rc = main(["fleet", str(store_dir), "--webhook", server])
        assert rc == 0
        assert "webhook notified: HTTP 200" in capsys.readouterr().out
        assert len(_Capture.received) == 1


class TestFleetJson:
    def test_fleet_json_output(self, populated, tmp_path, capsys):
        from approximately.cli import main

        store_dir = tmp_path / "s1"
        rc = main(["fleet", str(store_dir), "--json"])
        assert rc == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["stores"][0]["traces"] == 1
        assert "worsening_stores" in payload

    def test_webhook_and_json_share_payload(self, populated, tmp_path,
                                            server, capsys):
        from approximately.cli import main

        main(["fleet", str(tmp_path / "s1"), "--json"])
        cli_payload = json.loads(capsys.readouterr().out)
        main(["fleet", str(tmp_path / "s1"), "--webhook", server])
        posted = json.loads(_Capture.received[-1]["body"])
        for key in ("stores", "worsening_stores"):
            assert cli_payload[key] == posted[key]


class TestRetry:
    def test_transport_failure_retried_then_raises(self, populated,
                                                   monkeypatch):
        import urllib.error

        import approximately.fleet as fleet

        attempts = []
        class FakeResponse:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        def flaky(request, timeout=None):
            attempts.append(1)
            if len(attempts) < 2:
                raise urllib.error.URLError("temporary")
            return FakeResponse()

        monkeypatch.setattr(fleet.urllib.request, "urlopen", flaky)
        status = notify_webhook(populated, "http://127.0.0.1:1/x",
                                timeout=1.0)
        assert status == "200" and len(attempts) == 2

    def test_exhausted_retries_raise_with_count(self, populated,
                                                monkeypatch):
        import urllib.error

        import approximately.fleet as fleet

        def always_down(request, timeout=None):
            raise urllib.error.URLError("down")

        monkeypatch.setattr(fleet.urllib.request, "urlopen", always_down)
        with pytest.raises(RuntimeError, match="after 2 attempts"):
            notify_webhook(populated, "http://127.0.0.1:1/x", timeout=1.0)
