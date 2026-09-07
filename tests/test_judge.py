"""Judge integration tests against a local fake OpenAI-compatible server.

These run the real ``openai`` client against a stdlib HTTP server, covering
the full judge path: protocol handling, verdict parsing, arbitration with the
rule engine, and every failure/degradation mode.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

openai = pytest.importorskip("openai")

from approximately.attributor import attribute
from approximately.judge import JudgeError, judge_trace

MODES_JSON = json.dumps(
    {"mode_id": "FM-2.6", "step_index": 3, "rationale": "said X did Y",
     "confidence": 0.66}
)


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

    def log_message(self, *args):  # silence
        pass


@pytest.fixture
def fake_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeOpenAIHandler)
    server.content = MODES_JSON
    server.status = 200
    server.requests = []
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()


def _base_url(server) -> str:
    return f"http://127.0.0.1:{server.server_address[1]}/v1"


def test_judge_parses_valid_verdict(failing_trace, fake_server):
    verdict = judge_trace(failing_trace, model="fake-model",
                          base_url=_base_url(fake_server), api_key="test")
    assert verdict.detection.mode_id == "FM-2.6"
    assert verdict.detection.step_index == 3
    assert verdict.detection.confidence == pytest.approx(0.66)
    assert "said X did Y" in verdict.detection.evidence[0]
    # the request carried the MAST taxonomy and the trace payload
    sent = fake_server.requests[0]
    assert sent["model"] == "fake-model"
    system_prompt = sent["messages"][0]["content"]
    assert "FM-1.3" in system_prompt and "MAST taxonomy" in system_prompt
    trace_payload = json.loads(sent["messages"][1]["content"])
    assert trace_payload["task"] == failing_trace.task


def test_judge_agreement_boosts_confidence(failing_trace, fake_server):
    fake_server.content = json.dumps(
        {"mode_id": "FM-1.3", "step_index": 2, "rationale": "same calls",
         "confidence": 0.9}
    )
    report = attribute(failing_trace, use_judge=True,
                       model="fake", base_url=_base_url(fake_server),
                       api_key="test")
    assert report.judge_used is True
    assert report.disagreement is None
    top = report.detections[0]
    assert top.mode_id == "FM-1.3"
    assert top.confidence >= 0.9  # rule 0.8 + agreement bonus
    assert top.confidence < 1.0
    assert any("judge" in ev for ev in top.evidence)


def test_judge_conflict_is_recorded_not_hidden(failing_trace, fake_server):
    fake_server.content = MODES_JSON  # FM-2.6 vs rules' FM-1.3
    report = attribute(failing_trace, use_judge=True,
                       model="fake", base_url=_base_url(fake_server),
                       api_key="test")
    assert report.judge_used is True
    assert report.disagreement is not None
    assert "FM-1.3" in report.disagreement and "FM-2.6" in report.disagreement
    modes = {d.mode_id for d in report.detections}
    assert {"FM-1.3", "FM-2.6"} <= modes


def test_judge_survives_prose_wrapped_json(failing_trace, fake_server):
    fake_server.content = f"Sure! Here is my verdict:\n{MODES_JSON}\nHope that helps."
    verdict = judge_trace(failing_trace, base_url=_base_url(fake_server),
                          api_key="test")
    assert verdict.detection.mode_id == "FM-2.6"


def test_judge_coerces_hostile_field_types(failing_trace, fake_server):
    fake_server.content = json.dumps(
        {"mode_id": "FM-9.9", "step_index": "not-a-number",
         "confidence": "way-too-high", "rationale": None}
    )
    verdict = judge_trace(failing_trace, base_url=_base_url(fake_server),
                          api_key="test")
    assert verdict.detection.mode_id == "OTHER"       # unknown mode -> OTHER
    assert verdict.detection.step_index == 0
    assert verdict.detection.confidence == 0.5        # invalid -> default
    assert "None" in verdict.detection.evidence[0]    # null rationale str()


def test_judge_malformed_json_raises_judgeerror(failing_trace, fake_server):
    fake_server.content = "I think the agent repeated itself, probably FM-1.3."
    with pytest.raises(JudgeError):
        judge_trace(failing_trace, base_url=_base_url(fake_server), api_key="test")
    # ...and attribution degrades to rules instead of crashing
    report = attribute(failing_trace, use_judge=True,
                       model="fake", base_url=_base_url(fake_server),
                       api_key="test")
    assert report.primary_mode.id == "FM-1.3"
    assert report.judge_used is False


def test_judge_http_error_raises_judgeerror(failing_trace, fake_server):
    fake_server.status = 500
    with pytest.raises(JudgeError):
        judge_trace(failing_trace, base_url=_base_url(fake_server), api_key="test")


def test_judge_connection_refused_raises_judgeerror(failing_trace):
    with pytest.raises(JudgeError):
        judge_trace(failing_trace, base_url="http://127.0.0.1:9/v1",
                    api_key="test", )


def test_judge_wraps_missing_api_key_as_judgeerror(failing_trace, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(JudgeError):
        judge_trace(failing_trace, base_url="http://127.0.0.1:9/v1",
                    api_key=None)
