"""Shared fake OpenAI-compatible server (stdlib) for judge/teacher tests."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

try:
    import openai  # noqa: F401
    HAS_OPENAI = True
except ImportError:
    HAS_OPENAI = False


class FakeOpenAIHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("content-length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        server = self.server
        server.requests.append(json.loads(raw) if raw else {})
        if server.status != 200:
            self.send_response(server.status)
            self.send_header("content-length", "0")
            self.end_headers()
            return
        payload = json.dumps({
            "id": "chatcmpl-1",
            "object": "chat.completion",
            "model": server.requests[-1].get("model", "fake"),
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": server.content},
                "finish_reason": "stop",
            }],
        }).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        pass


@pytest.fixture
def fake_openai():
    """Yields a live server with settable .content / .status / .requests."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeOpenAIHandler)
    server.content = '{"mode_id": "FM-1.3", "step_index": 0, "confidence": 0.9}'
    server.status = 200
    server.requests = []
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server
    server.shutdown()
    server.server_close()


@pytest.fixture
def openai_url(fake_openai):
    """Skip-dependent base_url fixture: requires the openai package."""
    if not HAS_OPENAI:
        pytest.skip("openai not installed")
    return f"http://127.0.0.1:{fake_openai.server_address[1]}/v1"
