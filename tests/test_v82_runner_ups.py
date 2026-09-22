"""v82: runner-up hypotheses — attribution is a ranking, not an oracle.

When detectors fire for several modes, the report now carries the
non-primary candidates (mode, detection count, max confidence), shown
via `attribute --top N` and in the MCP attribute payload.
"""

import json

from approximately.attributor import attribute
from approximately.cli import build_parser
from approximately.mcp_server import ServerContext, handle_request
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _two_mode_trace():
    rec = Recorder("repair the flaky suite", save=False)
    # FM-1.3: identical (tool, args) repeated with success results
    rec.tool("bash", {"cmd": "pytest -k flaky"}, result="1 failed")
    rec.tool("bash", {"cmd": "pytest -k flaky"}, result="1 failed")
    # FM-2.5: peer request requiring ack, then the actor acted on it
    rec.message("planner", "coder", "please apply the patch",
                requires_ack=True)
    rec.tool("write_draft", {"topic": "patch"}, result="applied")
    rec.respond("gave up", success=False)
    return rec.trace


def test_runner_ups_present_and_exclude_primary():
    report = attribute(_two_mode_trace())
    modes = {d.mode_id for d in report.detections}
    assert len(modes) >= 2, f"fixture must fire 2+ modes, got {modes}"
    assert all(r["mode"] != report.primary_mode.id
               for r in report.runner_ups)
    for r in report.runner_ups:
        assert r["mode"] in modes
        assert 0.0 <= r["max_confidence"] <= 1.0
        assert r["detections"] >= 1


def test_single_mode_trace_has_no_runner_ups():
    rec = Recorder("clean fail", save=False)
    rec.respond("gave up", success=False)
    report = attribute(rec.trace)
    assert report.runner_ups == []


def test_to_dict_carries_runner_ups():
    body = attribute(_two_mode_trace()).to_dict()
    assert isinstance(body["runner_ups"], list)


def test_cli_attribute_top_flag(tmp_path, capsys):
    store = TraceStore(str(tmp_path / "s"))
    trace = _two_mode_trace()
    store.save(trace)
    parser = build_parser()
    args = parser.parse_args(["attribute", str(store.directory / trace.id),
                              "--top", "2"])
    assert args.func(args) == 0
    out = capsys.readouterr().out
    assert "RUNNER-UP HYPOTHESES" in out

    args = parser.parse_args(["attribute", str(store.directory / trace.id)])
    assert args.func(args) == 0
    assert "RUNNER-UP" not in capsys.readouterr().out  # default stays quiet


def test_mcp_attribute_payload_carries_runner_ups(tmp_path):
    store = TraceStore(str(tmp_path / "s"))
    trace = _two_mode_trace()
    store.save(trace)
    ctx = ServerContext(str(store.directory))
    resp = handle_request({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "attribute",
                   "arguments": {"trace": trace.id}},
    }, ctx)
    payload = json.loads(resp["result"]["content"][0]["text"])
    assert isinstance(payload["runner_ups"], list)
