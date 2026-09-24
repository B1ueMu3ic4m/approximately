"""v96: one verdict payload everywhere — CLI `verify <id> --json` and
the MCP `verify` tool share `integrity.verdict_payload`.

Before, the MCP tool answered `{"verdict": ...}` with the raw chain
result and nothing else — no detail, no chain finals, no rollback,
no ledger health, no key support — while the CLI knew the whole
six-rung ladder. Now both render the same object, and wrong-key
finally lands in the locked-not-broken family (exit 3) instead of
masquerading as TAMPERED.
"""

from __future__ import annotations

import argparse
import json

from approximately.cli import cmd_verify
from approximately.integrity import sign
from approximately.mcp_server import ServerContext, handle_request
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _store_with(tmp_path, tid="k-1", key=None):
    store = TraceStore(str(tmp_path / "traces"))
    rec = Recorder("verdict parity fixture", save=False)
    rec.trace.id = tid
    rec.tool("bash", {"cmd": "ls"}, result="ok")
    rec.respond("done", success=True)
    sign(rec.trace, key=key) if key else sign(rec.trace)
    store.save(rec.trace)
    return store


def _key_file(tmp_path, content: bytes):
    path = tmp_path / "key.hex"
    path.write_bytes(content)
    return str(path)


def _mcp_payload(store, trace="k-1", key_file=None):
    arguments = {"trace": trace, "store": str(store.directory)}
    if key_file:
        arguments["key_file"] = key_file
    resp = handle_request({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "verify", "arguments": arguments},
    }, ServerContext("."))
    assert resp["result"]["isError"] is False, resp["result"]
    return json.loads(resp["result"]["content"][0]["text"])


def test_intact_parity(tmp_path, capsys):
    store = _store_with(tmp_path)
    args = argparse.Namespace(store=str(store.directory), trace="k-1",
                              key_file=None, all=False, json=True,
                              since=None)
    assert cmd_verify(args) == 0
    cli = json.loads(capsys.readouterr().out)
    mcp = _mcp_payload(store)
    assert mcp == cli
    assert mcp["verdict"] == "intact"
    assert mcp["authenticated"] is False
    assert mcp["ledger"]["intact"] is True


def test_keyed_parity_with_key(tmp_path, capsys):
    key_file = _key_file(tmp_path, b"parity-key-2026")
    store = _store_with(tmp_path, key=b"parity-key-2026")
    args = argparse.Namespace(store=str(store.directory), trace="k-1",
                              key_file=key_file, all=False, json=True,
                              since=None)
    assert cmd_verify(args) == 0
    cli = json.loads(capsys.readouterr().out)
    mcp = _mcp_payload(store, key_file=key_file)
    assert mcp == cli
    assert mcp["verdict"] == "intact"
    assert mcp["authenticated"] is True


def test_wrong_key_is_locked_not_tampered(tmp_path, capsys):
    key_file = _key_file(tmp_path, b"new-key")
    store = _store_with(tmp_path, key=b"old-key")
    args = argparse.Namespace(store=str(store.directory), trace="k-1",
                              key_file=key_file, all=False, json=True,
                              since=None)
    assert cmd_verify(args) == 3
    payload = json.loads(capsys.readouterr().out)
    assert payload["verdict"] == "wrong-key"
    assert payload["intact"] is False


def test_mcp_tampered_carries_finals(tmp_path):
    store = _store_with(tmp_path)
    path = store.directory / "k-1.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["steps"][0]["result"] = "forged"
    path.write_text(json.dumps(data), encoding="utf-8")
    payload = _mcp_payload(store)
    assert payload["verdict"] == "tampered"
    assert payload["expected_final"] != payload["actual_final"]
    assert "no longer matches" in payload["detail"]


def test_mcp_rolled_back(tmp_path):
    store = _store_with(tmp_path)
    v1_payload = (store.directory / "k-1.json").read_text("utf-8")
    old_root = store.load("k-1").meta["integrity"]["final"]
    rec = Recorder("verdict parity fixture v2", save=False)
    rec.trace.id = "k-1"
    rec.tool("bash", {"cmd": "ls"}, result="changed")
    rec.respond("v2", success=True)
    sign(rec.trace)
    store.save(rec.trace)
    from approximately.ledger import EvidenceLedger

    ledger = EvidenceLedger(store.directory)
    ledger.append("k-1", old_root)
    ledger.append("k-1", store.load("k-1").meta["integrity"]["final"])
    (store.directory / "k-1.json").write_text(v1_payload, "utf-8")
    payload = _mcp_payload(store)
    assert payload["verdict"] == "rolled-back"
    assert payload["intact"] is True


def test_prose_wrong_key_says_wrong_key(tmp_path, capsys):
    from approximately.cli import build_parser

    key_file = _key_file(tmp_path, b"new-key")
    store = _store_with(tmp_path, key=b"old-key")
    args = build_parser().parse_args(
        ["verify", "--store", str(store.directory),
         "--key-file", key_file, "k-1"])
    assert args.func(args) == 3
    out = capsys.readouterr().out
    assert "WRONG-KEY" in out
    assert "TAMPERED" not in out
