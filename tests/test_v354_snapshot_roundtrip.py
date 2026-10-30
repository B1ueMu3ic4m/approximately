"""v354: the backup carries the whole working set, byte for byte.

The snapshot now includes the receiver's archive and its rotated
predecessors (v3.50.0) beside the traces, annotations, ledger and
price catalog. The round trip is pinned end to end: snapshot ->
restore -> every sidecar byte-identical, the catalog loads, the
archive stats agree, and the restored store verifies.
"""

import json
import tempfile
import zipfile
from pathlib import Path

from approximately.prices import load_catalog, save_catalog
from approximately.recorder import Recorder
from approximately.snapshot import restore, snapshot, verify_snapshot
from approximately.store import TraceStore


def _populated_store():
    store = TraceStore(tempfile.mkdtemp())
    rec = Recorder("round trip", store=store)
    rec.tool("sh", {}, result="ok")
    rec.respond("done", success=True)
    store.save(rec.trace)
    store.annotate(rec.trace.id, "reviewed")
    save_catalog(store.directory, {"gpt-x": 0.5})
    rows = [{"received_at": 1.0 + i, "verified": i % 2 == 0,
             "kind": "spool", "payload": {}} for i in range(4)]
    for name, content in (
            ("webhook-log.jsonl",
             "\n".join(json.dumps(r) for r in rows) + "\n"),
            ("webhook-log.jsonl.1",
             json.dumps({"received_at": 0.0, "verified": False,
                         "kind": "old", "payload": {}}) + "\n")):
        (store.directory / name).write_text(content, encoding="utf-8")
    return store


def test_restore_brings_every_sidecar_back_byte_identical():
    store = _populated_store()
    snap = Path(tempfile.mkdtemp()) / "snap.zip"
    report = snapshot(store.directory, snap)
    names = set(report["members"] if isinstance(
        report["members"], list) else [])
    manifest = json.loads(zipfile.ZipFile(snap).read("manifest.json"))
    names = set(manifest["members"])
    for expected in ("annotations.jsonl", "prices.json",
                     "webhook-log.jsonl", "webhook-log.jsonl.1"):
        assert expected in names, expected
    verdict = verify_snapshot(snap)
    assert not verdict[1], "the fresh snapshot verifies clean"

    into = Path(tempfile.mkdtemp()) / "restored"
    restore(snap, into)
    for name in ("webhook-log.jsonl", "webhook-log.jsonl.1",
                 "annotations.jsonl", "prices.json"):
        original = (store.directory / name).read_bytes()
        assert (into / name).read_bytes() == original, name
    assert load_catalog(into) == {"gpt-x": 0.5}
    from approximately.receiver import archive_stats

    assert archive_stats(into / "webhook-log.jsonl")["rows"] == 4
    assert archive_stats(into / "webhook-log.jsonl.1")["rows"] == 1
    restored_store = TraceStore(into)
    assert restored_store.list_traces()[0].task == "round trip"
    assert restored_store.annotations()[0]["note"] == "reviewed"
