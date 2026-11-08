"""v380: the receiving half closes the evidence loop.

``webhook-ship`` posts a trace; ``inbox-import`` brings it home:
a plan by default (reading is not deciding — retention's shape),
--apply to import, verified rows only (an open tap's rows could
be anything), already-present ids never re-imported, and every
import saves with stamp=False — foreign evidence keeps its own
integrity chain, never re-stamped by our key. Ship, receive,
import: one signed arc.
"""

import argparse
import json
import tempfile
from pathlib import Path

from approximately.cli import cmd_inbox_import, cmd_webhook_ship
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _keyfile():
    path = Path(tempfile.mkdtemp()) / "key"
    path.write_bytes(b"arc-key")
    return str(path)


def _store_with_traces(n=2):
    store = TraceStore(tempfile.mkdtemp())
    for i in range(n):
        rec = Recorder(f"shipped task {i}", store=store)
        rec.tool("sh", {"cmd": f"run {i}"}, result="ok")
        rec.respond("done", success=True)
        store.save(rec.trace)
    return store


def _ship_all(sender, url):
    for trace in sender.list_traces():
        args = argparse.Namespace(trace=trace.id, url=url,
                                  key_file=_keyfile(),
                                  store=str(sender.directory))
        assert cmd_webhook_ship(args) == 0


def _import_args(receiver_dir, **kw):
    base = {"trace": None, "url": None, "key_file": None,
            "store": str(receiver_dir), "archive": None,
            "apply": False, "allow_unverified": False,
            "include_rotated": False, "json": False}
    base.update(kw)
    return argparse.Namespace(**base)


def test_plan_then_apply_imports_shipped_traces(capsys):
    from approximately.receiver import serve

    receiver_dir = TraceStore(tempfile.mkdtemp()).directory
    archive = receiver_dir / "webhook-log.jsonl"
    server, _state = serve(archive, key=b"arc-key", port=0)
    url = f"http://127.0.0.1:{server.server_address[1]}"
    sender = _store_with_traces()
    try:
        _ship_all(sender, url)
    finally:
        server.shutdown()

    # plan: reading is not deciding
    assert cmd_inbox_import(_import_args(receiver_dir)) == 0
    plan_out = capsys.readouterr().out
    assert "2 shipment(s), 2 importable" in plan_out
    assert "dry run - add --apply to import" in plan_out
    assert "imported" not in plan_out.split("dry run")[0].split(
        "shipment(s)")[0]

    # the receiver's store does not have them yet
    assert len(TraceStore(str(receiver_dir)).list_traces()) == 0

    # apply: the arc closes
    assert cmd_inbox_import(_import_args(receiver_dir,
                                         apply=True)) == 0
    out = capsys.readouterr().out
    assert "stamp=False: foreign evidence keeps its own chain" \
        in out
    imported = TraceStore(str(receiver_dir)).list_traces()
    assert len(imported) == 2
    tasks = sorted(t.task for t in imported)
    assert tasks == ["shipped task 0", "shipped task 1"]


def test_imported_evidence_is_not_restamped():
    from approximately.receiver import serve

    receiver_dir = TraceStore(tempfile.mkdtemp()).directory
    archive = receiver_dir / "webhook-log.jsonl"
    server, _state = serve(archive, key=b"arc-key", port=0)
    url = f"http://127.0.0.1:{server.server_address[1]}"
    sender = _store_with_traces(1)
    original = sender.list_traces()[0]
    sender_integrity = json.dumps(original.meta.get("integrity"),
                                  sort_keys=True)
    try:
        _ship_all(sender, url)
    finally:
        server.shutdown()
    cmd_inbox_import(_import_args(receiver_dir, apply=True))
    arrived = TraceStore(str(receiver_dir)).list_traces()[0]
    assert json.dumps(arrived.meta.get("integrity"),
                      sort_keys=True) == sender_integrity, \
        "the trace keeps the sender's chain, byte for byte"


def test_already_present_ids_are_never_re_imported(capsys):
    from approximately.receiver import serve

    receiver_dir = TraceStore(tempfile.mkdtemp()).directory
    archive = receiver_dir / "webhook-log.jsonl"
    server, _state = serve(archive, key=b"arc-key", port=0)
    url = f"http://127.0.0.1:{server.server_address[1]}"
    sender = _store_with_traces(1)
    original_id = sender.list_traces()[0].id
    try:
        _ship_all(sender, url)
    finally:
        server.shutdown()
    # the trace is already in the local store: present, skipped
    local = TraceStore(str(receiver_dir))
    from approximately.trace import Trace

    local.save(Trace.from_dict(
        json.loads(json.dumps(
            sender.list_traces()[0].to_dict()))), stamp=False)
    assert cmd_inbox_import(_import_args(receiver_dir)) == 0
    out = capsys.readouterr().out
    assert "1 shipment(s), 0 importable" in out
    assert f"{original_id}" in out and "[present]" in out
    assert len(local.list_traces()) == 1


def test_open_tap_rows_are_refused_without_the_override(capsys):
    from approximately.receiver import serve

    receiver_dir = TraceStore(tempfile.mkdtemp()).directory
    archive = receiver_dir / "webhook-log.jsonl"
    # the open tap: no key on the receiver, everything unverified
    server, _state = serve(archive, key=None, port=0)
    url = f"http://127.0.0.1:{server.server_address[1]}"
    sender = _store_with_traces(1)
    try:
        _ship_all(sender, url)
    finally:
        server.shutdown()
    assert cmd_inbox_import(_import_args(receiver_dir)) == 0
    plan_out = capsys.readouterr().out
    assert "unverified-skipped" in plan_out
    assert len(TraceStore(str(receiver_dir)).list_traces()) == 0

    # the override imports loudly
    assert cmd_inbox_import(_import_args(
        receiver_dir, apply=True, allow_unverified=True)) == 0
    captured = capsys.readouterr()
    assert "could be anything" in captured.err
    assert len(TraceStore(str(receiver_dir)).list_traces()) == 1
