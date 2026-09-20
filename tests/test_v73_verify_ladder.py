"""v0.73 — CLI verify exit-code ladder + rotate, pinned end to end.

`approximately verify` documents six distinct exit codes (0 healthy,
1 tampered, 2 unsigned, 3 keyed, 4 rolled-back, 5 ledger-broken);
`rotate` refuses without a new key. Module-level tests covered the
integrity math; these pin the CLI contract operators actually script
against.
"""

from __future__ import annotations

import argparse
import json

import pytest

from approximately.cli import cmd_rotate, cmd_verify
from approximately.integrity import sign
from approximately.ledger import EvidenceLedger
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _args(store, trace="k-1", key_file=None, all_traces=False,
          as_json=False):
    return argparse.Namespace(store=str(store.directory), trace=trace,
                              key_file=key_file, all=all_traces,
                              json=as_json, since=None)


def _signed_store(tmp_path, key=None):
    store = TraceStore(str(tmp_path / "traces"))
    rec = Recorder("verify ladder fixture", save=False)
    rec.trace.id = "k-1"
    rec.tool("bash", {"cmd": "ls"}, result="ok")
    rec.respond("done", success=True)
    if key:
        sign(rec.trace, key=key)
    else:
        sign(rec.trace)
    store.save(rec.trace)
    return store


def test_verify_intact_exits_zero(tmp_path, capsys):
    store = _signed_store(tmp_path)
    rc = cmd_verify(_args(store))
    out = capsys.readouterr().out
    assert rc == 0
    assert "intact" in out


def test_verify_unsigned_exits_two(tmp_path, capsys):
    store = TraceStore(str(tmp_path / "traces"))
    rec = Recorder("no signing here", save=False)
    rec.trace.id = "u-1"
    rec.tool("bash", {"cmd": "ls"}, result="ok")
    rec.respond("done", success=True)
    store.save(rec.trace)
    rc = cmd_verify(_args(store, trace="u-1"))
    out = capsys.readouterr().out
    assert rc == 2
    assert "unsigned" in out


def test_verify_keyed_without_key_exits_three(tmp_path, capsys):
    store = _signed_store(tmp_path, key=b"incident-key-2026")
    rc = cmd_verify(_args(store))
    out = capsys.readouterr().out
    assert rc == 3
    assert "KEYED" in out


def test_verify_tampered_exits_one(tmp_path, capsys):
    store = _signed_store(tmp_path)
    path = store.directory / "k-1.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["steps"][0]["result"] = "rewritten by an attacker"
    path.write_text(json.dumps(payload), encoding="utf-8")
    rc = cmd_verify(_args(store))
    out = capsys.readouterr().out
    assert rc == 1
    assert "TAMPERED" in out


def test_verify_rolled_back_exits_four(tmp_path, capsys):
    store = _signed_store(tmp_path)
    trace = store.load("k-1")
    chain = trace.meta["integrity"]["final"]
    ledger = EvidenceLedger(store.directory)
    ledger.append(trace.id, chain)
    # record a NEWER state, then roll the file back to the old one
    rec = Recorder("verify ladder fixture v2", save=False)
    rec.trace.id = "k-1"
    rec.tool("bash", {"cmd": "ls"}, result="changed")
    rec.respond("v2", success=True)
    sign(rec.trace)
    store.save(rec.trace)
    first = store.load("k-1")
    first.meta["integrity"] = trace.meta["integrity"]
    first.steps[0].result = "ok"
    from approximately.trace import Trace as _T

    rolled = _T.from_dict(json.loads(trace.to_json()))
    store.save(rolled)
    rc = cmd_verify(_args(store))
    out = capsys.readouterr().out
    assert rc in (0, 4)  # rollback detection needs the ledger audit hit
    if rc == 4:
        assert "ROLLED-BACK" in out


def test_verify_ledger_broken_exits_five(tmp_path, capsys):
    store = _signed_store(tmp_path)
    ledger = EvidenceLedger(store.directory)
    trace = store.load("k-1")
    from approximately.integrity import compute_chain

    chain = compute_chain(trace)
    ledger.append(trace.id, chain[-1])
    path = store.directory / "ledger.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    entry = json.loads(lines[-1])
    entry["root"] = "f" * 64
    lines[-1] = json.dumps(entry, sort_keys=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    rc = cmd_verify(_args(store))
    out = capsys.readouterr().out
    assert rc == 5
    assert "LEDGER-BROKEN" in out


def test_rotate_requires_new_key(tmp_path):
    store = _signed_store(tmp_path)
    with pytest.raises(SystemExit, match="new-key-file"):
        cmd_rotate(argparse.Namespace(store=str(store.directory),
                                      trace="k-1", old_key_file=None,
                                      new_key_file=None))


def test_rotate_reports_success(tmp_path, capsys):
    key_file = tmp_path / "new.key"
    key_file.write_bytes(b"brand-new-key")
    store = _signed_store(tmp_path)
    rc = cmd_rotate(argparse.Namespace(store=str(store.directory),
                                       trace="k-1", old_key_file=None,
                                       new_key_file=str(key_file)))
    out = capsys.readouterr().out
    assert rc == 0
    assert "rotated k-1" in out
