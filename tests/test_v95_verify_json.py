"""v95: `verify <id> --json` — the single-trace verdict as data.

The --all audit already emitted JSON; a per-trace check (the thing a
CI job runs on one suspicious record) still printed prose. Now every
rung of the six-exit-code ladder has a machine-readable verdict with
the same codes, so scripts can branch on `verdict` instead of
grepping for TAMPERED.
"""

from __future__ import annotations

import argparse
import json

from approximately.cli import cmd_verify
from approximately.integrity import sign
from approximately.ledger import EvidenceLedger
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _args(store, trace, key_file=None):
    return argparse.Namespace(store=str(store.directory), trace=trace,
                              key_file=key_file, all=False,
                              json=True, since=None)


def _store_with(tmp_path, tid="k-1", signed=True):
    store = TraceStore(str(tmp_path / "traces"))
    rec = Recorder("verify json fixture", save=False)
    rec.trace.id = tid
    rec.tool("bash", {"cmd": "ls"}, result="ok")
    rec.respond("done", success=True)
    if signed:
        sign(rec.trace)
    store.save(rec.trace)
    return store


def _run(capsys):
    out = capsys.readouterr().out
    return json.loads(out)


def test_intact_verdict(tmp_path, capsys):
    store = _store_with(tmp_path)
    assert cmd_verify(_args(store, "k-1")) == 0
    payload = _run(capsys)
    assert payload["verdict"] == "intact"
    assert payload["intact"] is True
    assert payload["rollback"] is False
    assert payload["actual_final"]
    assert payload["ledger"]["intact"] is True


def test_unsigned_verdict(tmp_path, capsys):
    store = _store_with(tmp_path, tid="u-1", signed=False)
    assert cmd_verify(_args(store, "u-1")) == 2
    payload = _run(capsys)
    assert payload["verdict"] == "unsigned"
    assert payload["intact"] is False


def test_tampered_verdict(tmp_path, capsys):
    store = _store_with(tmp_path)
    path = store.directory / "k-1.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["steps"][0]["result"] = "forged"
    path.write_text(json.dumps(data), encoding="utf-8")
    assert cmd_verify(_args(store, "k-1")) == 1
    payload = _run(capsys)
    assert payload["verdict"] == "tampered"
    assert payload["intact"] is False
    assert payload["expected_final"] != payload["actual_final"]


def test_rolled_back_verdict(tmp_path, capsys):
    store = _store_with(tmp_path)
    v1_payload = (store.directory / "k-1.json").read_text("utf-8")
    old_root = store.load("k-1").meta["integrity"]["final"]
    rec = Recorder("verify json fixture v2", save=False)
    rec.trace.id = "k-1"
    rec.tool("bash", {"cmd": "ls"}, result="changed")
    rec.respond("v2", success=True)
    sign(rec.trace)
    store.save(rec.trace)
    new_root = store.load("k-1").meta["integrity"]["final"]
    ledger = EvidenceLedger(store.directory)
    ledger.append("k-1", old_root)
    ledger.append("k-1", new_root)
    # roll the file back to v1 — hashes valid, state stale
    (store.directory / "k-1.json").write_text(v1_payload, "utf-8")
    assert cmd_verify(_args(store, "k-1")) == 4
    payload = _run(capsys)
    assert payload["verdict"] == "rolled-back"
    assert payload["intact"] is True


def test_text_output_unchanged(tmp_path, capsys):
    from approximately.cli import build_parser

    store = _store_with(tmp_path)
    args = build_parser().parse_args(
        ["verify", "--store", str(store.directory), "k-1"])
    assert args.func(args) == 0
    out = capsys.readouterr().out
    assert "intact" in out and "chain final" in out
    assert not out.lstrip().startswith("{")
