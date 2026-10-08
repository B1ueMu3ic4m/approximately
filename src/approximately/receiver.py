"""The receiving end of the signed channel.

Fleet summaries, tail failure announcements and shift digests all
travel one way: HMAC-signed JSON POSTs. ``webhook-serve`` is the
zero-dependency other end — a small HTTP server that verifies the
``X-Approximately-Signature`` header against the same ``load_key``
every poster uses, and archives what survives into a JSONL log.

Trust rules, in order:

- a configured key (``--key-file`` or ``APPROXIMATELY_SIGNING_KEY``)
  makes the server **verify-only**: an absent, malformed or wrong
  signature is refused with 401 and never archived — an unauthenticated
  writer must not be able to seed the ops log;
- with no key configured the server accepts and archives, marking
  every row ``"verified": false`` — useful for a first look, and
  honest about what it is (an open tap, not a trust boundary);
- the body must be JSON; a hostile body is refused without crashing
  the server. Anything the poster sends rides along verbatim in the
  archived row — the log is evidence of what was received, not of
  what was true.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional, Tuple


class ReceiverState:
    """What the server needs between requests: the verifying key
    (None = accept-and-mark-unverified) and the archive path."""

    def __init__(self, archive: Path,
                 key: Optional[bytes] = None):
        self.archive = archive
        self.key = key
        self.received = 0
        self.refused = 0

    def verify(self, body: bytes,
               signature: Optional[str]) -> Tuple[bool, str]:
        """(verified, verdict) for one request. With no key the
        verdict is ``unsigned-open``; with a key, anything but the
        exact ``sha256=<hex>`` of the body is ``refused``."""
        if self.key is None:
            return False, "unsigned-open"
        if not signature or not signature.startswith("sha256="):
            return False, "refused"
        expected = hmac.new(self.key, body,
                            hashlib.sha256).hexdigest()
        got = signature[len("sha256="):]
        if hmac.compare_digest(expected, got):
            return True, "verified"
        return False, "refused"


def make_handler(state: ReceiverState) -> type:
    """Build a handler class bound to one ReceiverState (per-test
    servers get fresh state; nothing is class-level)."""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path != "/health":
                self._reply(404, {"error": "not found"})
                return
            self._reply(200, {"ok": True,
                              "received": state.received,
                              "refused": state.refused,
                              "verify_mode": bool(state.key)})

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", 0) or 0)
            body = self.rfile.read(length) if length else b""
            verified, verdict = state.verify(
                body, self.headers.get("X-Approximately-Signature"))
            if verdict == "refused":
                state.refused += 1
                self._reply(401, {"error": "bad signature"})
                return
            try:
                payload = json.loads(body.decode("utf-8"))
                if not isinstance(payload, dict):
                    raise ValueError("payload must be a JSON object")
            except (ValueError, UnicodeDecodeError):
                state.refused += 1
                self._reply(400, {"error": "body must be a JSON "
                                           "object"})
                return
            row = {"received_at": time.time(),
                   "verified": verified,
                   "kind": payload.get("kind", "?"),
                   "payload": payload}
            state.archive.parent.mkdir(parents=True, exist_ok=True)
            with state.archive.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, ensure_ascii=False,
                                    sort_keys=True) + "\n")
            state.received += 1
            self._reply(200, {"received": True, "verified": verified})

        def _reply(self, status: int, body: dict) -> None:
            data = json.dumps(body).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args: Any) -> None:  # silenced
            pass

    return Handler


def serve(archive: Path, port: int = 0,
          key: Optional[bytes] = None) -> Tuple[ThreadingHTTPServer,
                                               ReceiverState]:
    """Bind the receiver; returns the server (call shutdown() from
    the controlling thread) and its state."""
    state = ReceiverState(archive, key=key)
    server = ThreadingHTTPServer(("127.0.0.1", port),
                                 make_handler(state))
    thread = __import__("threading").Thread(
        target=server.serve_forever, daemon=True)
    thread.start()
    return server, state
