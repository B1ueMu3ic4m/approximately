"""Night VI, round 10: the verdict reaches the agent side and the pulse.

The MCP doctor tool can now repair (hygiene + quarantine), so an
agent harness can clean its own store through the same door the CLI
uses; `status` carries the breach count so the ops pulse shows what
the live rails stopped.
"""

import argparse
import json

from approximately.budget import Budget
from approximately.cli import cmd_status
from approximately.doctor import QUARANTINE_DIR
from approximately.mcp_server import _TOOLS, ServerContext, _tool_doctor
from approximately.recorder import Recorder
from approximately.store import TraceStore


class _FakeCtx(ServerContext):
    def __init__(self, store_dir):
        super().__init__(str(store_dir))


def _seed(tmp_path, poison=False):
    store = TraceStore(tmp_path)
    budget = Budget(tokens=5, on_exceed="stamp")
    with Recorder("burn", model="m/1", store=store,
                  budget=budget) as rec:
        rec.tool("t", tokens=500)
        rec.respond("done", success=True)
    with Recorder("calm", model="m/1", store=store) as rec:
        rec.respond("done", success=True)
    if poison:
        (tmp_path / "broken.json").write_text("{nope", encoding="utf-8")
    return store


def test_mcp_doctor_schema_has_fix():
    doctor_tool = next(t for t in _TOOLS if t["name"] == "doctor")
    assert "fix" in doctor_tool["inputSchema"]["properties"]


def test_mcp_doctor_fix_quarantines(tmp_path):
    _seed(tmp_path, poison=True)
    payload = _tool_doctor(_FakeCtx(tmp_path), {"store": str(tmp_path),
                                                "fix": True})
    assert payload["quarantined"] == ["broken.json"]
    assert payload["corrupt"] == []
    assert payload["healthy"] is True
    assert (tmp_path / QUARANTINE_DIR / "broken.json").is_file()


def test_mcp_doctor_without_fix_only_reports(tmp_path):
    _seed(tmp_path, poison=True)
    payload = _tool_doctor(_FakeCtx(tmp_path), {"store": str(tmp_path)})
    assert payload["corrupt"] == ["broken.json"]
    assert payload["quarantined"] == []
    assert not (tmp_path / QUARANTINE_DIR).exists()


def test_status_payload_counts_breaches(tmp_path):
    _seed(tmp_path)
    store = TraceStore(tmp_path)
    traces = store.list_traces()
    from approximately.cli import _status_payload
    payload = _status_payload(store, traces, None)
    assert payload["budget_breaches"] == 1


def test_status_text_names_the_breaches(tmp_path, capsys):
    _seed(tmp_path)
    rc = cmd_status(argparse.Namespace(store=str(tmp_path), since=None,
                                       json=False, watch=False,
                                       digest_dir=None, prices=None,
                                       interval=30.0))
    out = capsys.readouterr().out
    assert rc == 0
    assert "budget breaches: 1 run(s) the live rails stopped" in out


def test_status_json_round_trips(tmp_path, capsys):
    _seed(tmp_path)
    rc = cmd_status(argparse.Namespace(store=str(tmp_path), since=None,
                                       json=True, watch=False,
                                       digest_dir=None, prices=None,
                                       interval=30.0))
    out = capsys.readouterr().out
    assert rc == 0
    payload = json.loads(out)
    assert payload["budget_breaches"] == 1
