"""v375: the ping verifies its own delivery.

A ping used to read the channel-global /stats back — under
concurrent traffic that count can be wrong in either direction
(another sender's rows inflate it, a rotated log deflates it),
so "1 row(s)" proved nothing about YOUR ping. The ping now
carries a random nonce and asks the scoped probe
(``/stats?kind=ping&contains=<nonce>``): a nonce matches only
the row it rode in on. A receiver that predates the query
filters falls back to the global readback, honestly labelled.
"""

import argparse
import json
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from approximately.cli import cmd_webhook_ping


def _receiver(key=None):
    from approximately.receiver import serve

    archive = Path(tempfile.mkdtemp()) / "webhook-log.jsonl"
    server, _state = serve(archive, key=key, port=0)
    port = server.server_address[1]
    return server, archive, f"http://127.0.0.1:{port}"


def _keyfile():
    path = Path(tempfile.mkdtemp()) / "key"
    path.write_bytes(b"ping-key")
    return str(path)


def _ping(url, message="hello"):
    args = argparse.Namespace(url=url, key_file=_keyfile(),
                              message=message, store=".")
    assert cmd_webhook_ping(args) == 0


def test_two_concurrent_pings_each_verify_their_own_row(capsys):
    # one shared buffer: capsys is not thread-safe, prints from
    # both pings interleave here
    server, _archive, url = _receiver(key=b"ping-key")
    try:
        threads = [threading.Thread(target=_ping,
                                    args=(url, f"ping {i}"))
                   for i in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        out = capsys.readouterr().out
        assert out.count("1 row(s) matched this ping") == 2, \
            "each nonce matched exactly its own row, not the traffic"
    finally:
        server.shutdown()


def test_an_old_receiver_falls_back_to_the_global_readback(capsys):
    class OldReceiver(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0) or 0)
            self.rfile.read(length)
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"{}")

        def do_GET(self):
            if "?" in self.path:
                body = b'{"error": "no filters here"}'
                self.send_response(400)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            body = json.dumps({
                "archive": {"rows": 1, "verified": 1,
                            "malformed": 0}}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), OldReceiver)
    server.daemon_threads = True
    worker = threading.Thread(target=server.serve_forever,
                              daemon=True)
    worker.start()
    url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        _ping(url)
        out = capsys.readouterr().out
        assert "receiver archive: 1 row(s), 1 verified" in out, \
            "the global fallback, honestly labelled"
        assert "scoped to this ping" not in out
    finally:
        server.shutdown()


def test_a_receiver_that_loses_the_ping_says_so(capsys):
    # accepts the POST, never archives it: the scoped probe sees
    # zero rows and the ping refuses to call that a success
    class BlackHole(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0) or 0)
            self.rfile.read(length)
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"{}")

        def do_GET(self):
            body = json.dumps({
                "archive": {"rows": 0, "verified": 0,
                            "malformed": 0}}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), BlackHole)
    server.daemon_threads = True
    worker = threading.Thread(target=server.serve_forever,
                              daemon=True)
    worker.start()
    url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        _ping(url)
        captured = capsys.readouterr()  # one read consumes the buffer
        out, err = captured.out, captured.err
        assert "0 row(s) matched this ping" in out
        assert "found nothing" in err, \
            "an accepted-but-lost ping is a warning, not silence"
    finally:
        server.shutdown()
