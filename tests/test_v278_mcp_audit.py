"""Night VI, round 22: the audit reaches standing surfaces.

The MCP surface gains ``audit`` (39 tools) and ``init`` now wires a
nightly ``agent-audit.yml`` (cron 03:00) beside the PR gate — the
composed door is something a schedule runs, so both standing
surfaces carry it.
"""

import json

from approximately.budget import Budget
from approximately.mcp_server import (
    _TOOLS,
    ServerContext,
    _tool_audit,
)
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _store(tmp_path, poison=False):
    store = TraceStore(tmp_path / "s")
    budget = Budget(tokens=5)
    with Recorder("burn", model="m/1", store=store,
                  budget=budget) as rec:
        rec.tool("t", tokens=500)
        rec.respond("done", success=True)
    with Recorder("calm", model="m/1", store=store) as rec:
        rec.respond("done", success=True)
    if poison:
        (tmp_path / "s" / "dead.json").write_text("{nope",
                                                   encoding="utf-8")
    return store


def test_audit_tool_registered():
    assert "audit" in {t["name"] for t in _TOOLS}
    tool = next(t for t in _TOOLS if t["name"] == "audit")
    assert "fix" in tool["inputSchema"]["properties"]
    assert "spend_ceiling" in tool["inputSchema"]["properties"]


def test_audit_tool_composes(tmp_path):
    store = _store(tmp_path)
    payload = _tool_audit(ServerContext(str(store.directory)),
                          {"store": str(store.directory),
                           "max_budget_breaches": 0})
    assert payload["ok"] is False
    assert payload["doctor"]["healthy"] is True
    assert payload["gate"]["ok"] is False


def test_audit_tool_fix_repairs(tmp_path):
    store = _store(tmp_path, poison=True)
    payload = _tool_audit(ServerContext(str(store.directory)),
                          {"store": str(store.directory),
                           "fix": True})
    assert payload["doctor"]["quarantined"] == ["dead.json"]
    assert payload["doctor"]["healthy"] is True


def test_audit_tool_empty_store_refuses(tmp_path):
    empty = tmp_path / "nothing"
    empty.mkdir()
    try:
        _tool_audit(ServerContext(str(tmp_path)),
                    {"store": str(empty)})
        raise AssertionError("no refusal for empty store")
    except KeyError as exc:
        assert "proves nothing" in str(exc)


def test_audit_tool_forecast(tmp_path):
    store = _store(tmp_path)
    digest = tmp_path / "d"
    digest.mkdir()
    for i, spend in enumerate([5.0, 15.0]):
        line = json.dumps({
            "ts": 1791000000 + i * 86400,
            "stores": [{"name": "s", "path": "/x", "traces": 1,
                        "est_spend": spend,
                        "spend_unpriced_tokens": 0}],
            "worsening": []}, sort_keys=True)
        (digest / f"digest-2026100{i + 1}.jsonl").write_text(
            line + "\n", encoding="utf-8")
    payload = _tool_audit(ServerContext(str(store.directory)),
                          {"store": str(store.directory),
                           "digest_dir": str(digest),
                           "spend_ceiling": 10.0})
    assert payload["forecast"]["days_to_ceiling"] == 0
    assert payload["ok"] is False
