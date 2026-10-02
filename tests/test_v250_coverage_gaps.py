"""v250: the audit round — covering the paths only real life hits.

Coverage audit found the seams: the spool's REAL webhook path
(HMAC-signed, env key) had never been exercised — every prior test
injected a notify; the delivery-failure and Ctrl-C paths of the
watch loop were written but never run; and the markdown report's
rare cards (counterfactual, neighbours, annotations) had no render
pin.  This round runs the real paths, not stand-ins.
"""

import hashlib
import hmac
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import ClassVar

from approximately.anomaly import (
    detect_latency_anomalies,
    detect_token_anomalies,
)
from approximately.recorder import Recorder
from approximately.spool import _notify_spool, _primary_mode, watch_spool
from approximately.store import TraceStore


class _Capture(BaseHTTPRequestHandler):
    received: ClassVar[list] = []

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        type(self).received.append(
            {"body": self.rfile.read(length),
             "signature": self.headers.get(
                 "X-Approximately-Signature")})
        self.send_response(200)
        self.end_headers()

    def log_message(self, *args):
        pass


def test_real_spool_webhook_is_signed_and_shaped(tmp_path, monkeypatch):
    _Capture.received = []
    httpd = HTTPServer(("127.0.0.1", 0), _Capture)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    monkeypatch.setenv("APPROXIMATELY_SIGNING_KEY", "sekrit")
    store = TraceStore(tmp_path / "s")
    rec = Recorder("broken run", store=store, save=False)
    rec.tool("deploy", {}, error="boom")
    rec.respond("gave up", success=False)
    path = store.save(rec.trace)
    outcome = {"trace_ids": [path.stem], "imported": 1}
    try:
        _notify_spool(store, outcome, f"http://127.0.0.1:{httpd.server_port}")
    finally:
        httpd.shutdown()
    assert len(_Capture.received) == 1
    hit = _Capture.received[0]
    body = json.loads(hit["body"])
    assert body["kind"] == "spool"
    assert body["failures"][0]["trace_id"] == path.stem
    expected = hmac.new(b"sekrit", hit["body"],
                        hashlib.sha256).hexdigest()
    assert hit["signature"] == f"sha256={expected}"


def test_real_spool_webhook_without_key_is_unsigned(tmp_path,
                                                    monkeypatch):
    _Capture.received = []
    httpd = HTTPServer(("127.0.0.1", 0), _Capture)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    monkeypatch.delenv("APPROXIMATELY_SIGNING_KEY", raising=False)
    store = TraceStore(tmp_path / "s")
    rec = Recorder("plain", store=store, save=False)
    rec.respond("done", success=False)
    path = store.save(rec.trace)
    try:
        _notify_spool(store, {"trace_ids": [path.stem]},
                      f"http://127.0.0.1:{httpd.server_port}")
    finally:
        httpd.shutdown()
    assert _Capture.received[0]["signature"] is None


def test_primary_mode_survives_an_attribution_crash(tmp_path,
                                                    monkeypatch):
    import approximately.attributor as attributor

    store = TraceStore(tmp_path / "s")
    rec = Recorder("boom", store=store, save=False)
    rec.respond("done", success=False)
    store.save(rec.trace)
    trace = store.load(rec.trace.id)

    def explode(_trace):
        raise RuntimeError("detector plumbing on fire")

    monkeypatch.setattr(attributor, "attribute", explode)
    assert _primary_mode(trace) is None      # best-effort means best-effort


def test_watch_survives_webhook_delivery_failure(tmp_path, capsys):
    spool = tmp_path / "spool"
    spool.mkdir()
    rec = Recorder("broken", save=False)
    rec.respond("gave up", success=False)
    (spool / "run.jsonl").write_text(
        json.dumps(rec.trace.to_dict()) + "\n", encoding="utf-8")
    store = TraceStore(tmp_path / "s")

    def always_down(store, outcome, url):
        raise RuntimeError("endpoint on fire")

    code = watch_spool(store, spool, interval=0.0, max_passes=1,
                       webhook_url="http://127.0.0.1:1/x",
                       notify=always_down)
    assert code == 1                          # the gate still reports
    assert "delivery failed" in capsys.readouterr().err


def test_watch_ctrl_c_is_a_clean_stop(tmp_path, monkeypatch):
    spool = tmp_path / "spool"
    spool.mkdir()
    store = TraceStore(tmp_path / "s")
    import approximately.spool as spool_mod

    def interrupt(_seconds):
        raise KeyboardInterrupt

    monkeypatch.setattr(spool_mod.time, "sleep", interrupt)
    assert watch_spool(store, spool, interval=0.0, max_passes=None) == 0


def test_watch_failure_pass_reports_token_burns_line(tmp_path, capsys):
    from approximately.trace import Step, Trace

    spool = tmp_path / "spool"
    spool.mkdir()
    trace = Trace(task="loopy", id="loopy", created_at=1.0)
    for tokens in (100, 110, 90, 105, 95, 9000):
        trace.add(Step(kind="tool_call", tool="search",
                       tokens=tokens, latency_ms=40))
    trace.add(Step(kind="response", result="done"))
    trace.success = False
    (spool / "burn.jsonl").write_text(
        json.dumps(trace.to_dict()) + "\n", encoding="utf-8")
    store = TraceStore(tmp_path / "s")
    watch_spool(store, spool, interval=0.0, max_passes=1)
    assert "token burns:" in capsys.readouterr().out


def test_markdown_renders_rare_cards(tmp_path):
    from approximately.attributor import attribute
    from approximately.markdown_report import render_markdown
    from approximately.trace import Step, Trace

    store = TraceStore(tmp_path / "s")
    trace = Trace(task="loopy", id="md-1", created_at=1.0)
    for tokens in (100, 110, 90, 105, 95, 9000):
        trace.add(Step(kind="tool_call", tool="search",
                       tokens=tokens, latency_ms=40 + (tokens % 7)))
    trace.add(Step(kind="tool_call", tool="search", tokens=95,
                   latency_ms=40_000))
    trace.add(Step(kind="response", result="done"))
    trace.success = False
    store.save(trace)
    twin = Trace(task="loopy again (near-identical run)", id="md-0",
                 created_at=0.5)
    twin.add(Step(kind="tool_call", tool="search", tokens=100,
                  latency_ms=45))
    twin.add(Step(kind="response", result="done"))
    store.save(twin)
    store.annotate(trace.id, "retry loop", verdict="confirmed",
                   author="oncall")
    text = render_markdown(trace, attribute(trace), store=store)
    assert "Latency anomalies" in text
    assert "Token burn" in text
    assert "retry loop" in text
    assert "Nearest neighbours" in text


def test_markdown_silent_when_detectors_explode(tmp_path, monkeypatch):
    from approximately import markdown_report as mr
    from approximately.attributor import attribute
    from approximately.markdown_report import render_markdown

    rec = Recorder("calm", save=False)
    rec.respond("done", success=True)

    def explode(*a, **kw):
        raise RuntimeError("no ruler today")

    monkeypatch.setattr(mr, "detect_latency_anomalies", explode,
                        raising=False)
    monkeypatch.setattr(mr, "detect_token_anomalies", explode,
                        raising=False)
    text = render_markdown(rec.trace, attribute(rec.trace))
    assert "Latency anomalies" not in text


def test_per_trace_latency_uniform_sample_is_a_noop():
    # the per-trace detector's flat-line branch: every step
    # identical leaves no scale, and no anomalies are invented
    from approximately.trace import Step, Trace

    trace = Trace(task="uniform", id="uni-1", created_at=1.0)
    for _ in range(8):
        trace.add(Step(kind="tool_call", tool="search",
                       tokens=100, latency_ms=40))
    trace.add(Step(kind="response", result="done"))
    assert detect_latency_anomalies(trace) == []
    assert detect_token_anomalies(trace) == []
