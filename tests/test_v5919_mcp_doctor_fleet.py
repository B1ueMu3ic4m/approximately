"""v5919: the MCP doctor surface meets the fleet.

The audit family's last MCP gap: verify gained stores (v5.9.11),
handoff gained the fleet worklist (v5.9.14) — the doctor tool
still audited ONE store, so an agent checking every box's hygiene
made N calls and aggregated the verdicts itself. The doctor tool
gains ``stores``: a FLEET audit (one report per store, healthy =
every box healthy). Audit-ONLY by design — a repair needs an
operator looking at ONE box, so the fleet mode refuses fix=true.
The wire stays honest: a non-list item and a typo'd path answer
by name, the schema describes the key, and the single-store
shape is unchanged.
"""

import json

from approximately.mcp_server import _TOOLS, ServerContext, handle_request
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _clean(tmp_path, name):
    store = TraceStore(tmp_path / name)
    rec = Recorder(f"fleet {name}", model="m/1", store=store,
                   save=False)
    rec.tool("deploy", {}, result="ok")
    rec.respond("done", success=True)
    store.save(rec.trace)
    return store


def _call(ctx, arguments):
    payload = handle_request({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "doctor", "arguments": arguments},
    }, ctx)
    result = payload["result"]
    return (json.loads(result["content"][0]["text"]),
            result.get("isError", False))


def test_the_schema_describes_stores():
    doctor = next(t for t in _TOOLS if t["name"] == "doctor")
    assert "stores" in doctor["inputSchema"]["properties"], \
        "a client cannot discover a door the schema hides"


def test_a_fleet_audit_reports_each_box(tmp_path):
    _clean(tmp_path, "a")
    _clean(tmp_path, "b")
    ctx = ServerContext(str(tmp_path / "a"))
    data, is_error = _call(ctx, {"stores": [str(tmp_path / "a"),
                                            str(tmp_path / "b")]})
    assert is_error is False
    assert data["fleet"] is True and data["healthy"] is True
    assert [r["store"] for r in data["reports"]] == \
        [str(tmp_path / "a"), str(tmp_path / "b")]
    assert all(r["records"] == 1 for r in data["reports"])


def test_an_unhealthy_box_fails_the_fleet(tmp_path):
    _clean(tmp_path, "a")
    sick = _clean(tmp_path, "b")
    (sick.directory / "corrupt01ab.json").write_text(
        "{torn", encoding="utf-8")
    ctx = ServerContext(str(tmp_path / "a"))
    data, is_error = _call(ctx, {"stores": [str(tmp_path / "a"),
                                            str(tmp_path / "b")]})
    assert is_error is False, (
        "a finding is DATA on the fleet audit, not a tool failure")
    assert data["healthy"] is False
    sick_report = next(r for r in data["reports"]
                       if r["store"] == str(tmp_path / "b"))
    assert sick_report["corrupt"], "the finding names its box"


def test_the_fleet_audit_never_repairs(tmp_path):
    _clean(tmp_path, "a")
    sick = _clean(tmp_path, "b")
    (sick.directory / "corrupt01ab.json").write_text(
        "{torn", encoding="utf-8")
    (sick.directory / ".stale.lock").write_text(
        "dead", encoding="utf-8")
    ctx = ServerContext(str(tmp_path / "a"))
    _data, _is_error = _call(
        ctx, {"stores": [str(tmp_path / "a"), str(tmp_path / "b")],
              "fix": True})
    assert (sick.directory / "corrupt01ab.json").exists(), (
        "a repair needs an operator looking at ONE box: the fleet "
        "audit is audit-only, fix=true never crosses it")


def test_hostile_stores_answer_by_name(tmp_path):
    _clean(tmp_path, "a")
    ctx = ServerContext(str(tmp_path / "a"))
    bad, is_error = _call(ctx, {"stores": "not-a-list"})
    assert is_error and "stores must be a list of paths" in \
        json.dumps(bad)
    missing, missing_error = _call(
        ctx, {"stores": [str(tmp_path / "typo")]})
    assert missing_error and "store not found" in json.dumps(missing)


def test_without_stores_the_shape_is_unchanged(tmp_path):
    _clean(tmp_path, "a")
    ctx = ServerContext(str(tmp_path / "a"))
    data, is_error = _call(ctx, {})
    assert is_error is False
    assert "fleet" not in data, \
        "the single-store wire shape gains no key"
