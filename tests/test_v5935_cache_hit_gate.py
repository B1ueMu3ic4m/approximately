"""v5935: the judge cache's hit contract is gated — and the gate
caught a real bug on its first run.

The gate asks 24 distinct failures twice against a loopback-only
fake endpoint: pass one dials N times, pass two must dial ZERO —
every verdict answered from disk. On its first run the gate
failed: a verdict WITHOUT ``rationale`` wrote a cache entry the
readback refused (the shape check was stricter than the fresh
path, which coerces an absent rationale to ""), so every such
failure re-dialed the endpoint on every relabel — a cache that
never hits for a whole class of verdicts, billing silently. The
fix restores the symmetry (absent rationale reads like fresh;
present-but-garbage still misses), and the pins keep it dead.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from approximately.judge import cache_stats, judge_trace
from approximately.recorder import Recorder

try:
    import openai  # noqa: F401
    HAS_OPENAI = True
except ImportError:
    HAS_OPENAI = False


class _FakeEndpoint(BaseHTTPRequestHandler):
    content = '{"mode_id": "FM-1.3", "confidence": 0.9}'
    requests = 0

    def do_POST(self):
        self.rfile.read(int(self.headers.get("content-length", 0)))
        _FakeEndpoint.requests += 1
        body = json.dumps({
            "choices": [{"message": {"role": "assistant",
                                     "content": self.content}}],
        }).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture
def endpoint():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeEndpoint)
    _FakeEndpoint.requests = 0
    threading.Thread(target=server.serve_forever,
                     daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}/v1"
    server.shutdown()
    server.server_close()


def _failure(i=0):
    rec = Recorder(f"cache gate failure {i}", save=False)
    rec.tool("deploy", {"i": i}, result=None, error="boom")
    rec.respond("done", success=False)
    return rec.trace


def _ask(trace, base_url, cache):
    return judge_trace(trace, model="fake/1", base_url=base_url,
                       api_key="pin-only", cache_dir=cache)


def test_a_rationale_less_verdict_caches_and_hits(endpoint, tmp_path):
    if not HAS_OPENAI:
        pytest.skip("openai not installed")
    cache = tmp_path / "jcache"
    trace = _failure()
    cache_stats(reset=True)
    _ask(trace, endpoint, cache)
    dialed_cold = _FakeEndpoint.requests
    cache_stats(reset=True)
    _ask(trace, endpoint, cache)
    stats = cache_stats()
    assert dialed_cold == 1, "the cold ask dials once"
    assert _FakeEndpoint.requests == dialed_cold, \
        "the warm ask must be answered from disk, not re-dialed"
    assert stats == {"hits": 1, "misses": 0}, stats
    verdict = _ask(trace, endpoint, cache)
    assert verdict.rationale == "", \
        "an absent rationale reads like the fresh path's coercion"


def test_a_poisoned_rationale_still_misses(endpoint, tmp_path):
    if not HAS_OPENAI:
        pytest.skip("openai not installed")
    cache = tmp_path / "jcache"
    trace = _failure()
    _ask(trace, endpoint, cache)
    from approximately.judge import _cache_key

    path = cache / f"{_cache_key(trace, 'fake/1', 'strong')}.json"
    entry = json.loads(path.read_text(encoding="utf-8"))
    entry["payload"]["rationale"] = {"lie": True}
    path.write_text(json.dumps(entry), encoding="utf-8")
    cache_stats(reset=True)
    _ask(trace, endpoint, cache)
    stats = cache_stats()
    assert stats["hits"] == 0 and stats["misses"] == 1, stats
    assert _FakeEndpoint.requests == 2, \
        "a poisoned entry is a miss, and the miss re-dials"


def test_perf_gate_prints_the_judge_cache_line():
    if not HAS_OPENAI:
        pytest.skip("openai not installed")
    import subprocess
    import sys

    proc = subprocess.run(
        [sys.executable, str(Path(__file__).resolve().parent.parent
                             / "scripts" / "perf_gate.py")],
        capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0, proc.stdout[-400:]
    assert "perf-gate[judge-cache]" in proc.stdout
    assert "0 dial(s)" in proc.stdout, \
        "the gate's teeth: a warm pass that dials must fail it"
