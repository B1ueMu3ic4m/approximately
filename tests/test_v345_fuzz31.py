"""Fuzz 31: the doctor meets hostile archives.

The archive check reads whatever sits at ``webhook-log.jsonl`` —
and disks collect history: the file may be a directory, binary
garbage, a crash-truncated tail, a rotated entry that is itself a
directory, or a log with every kind of lie in its rows. The
contract under fuzz: the doctor never raises, the archive
findings stay truthful or absent, and ``healthy`` reflects the
store's own evidence, not the archive's hostility (the archive
belongs to the channel; the doctor counts, it does not judge).
"""

import json
import tempfile

from approximately.doctor import doctor
from approximately.store import TraceStore


def _store():
    return TraceStore(tempfile.mkdtemp())


def _report(store):
    return doctor(store.directory)


def test_archive_path_is_a_directory():
    store = _store()
    (store.directory / "webhook-log.jsonl").mkdir()
    report = _report(store)
    assert report.archive_rows == 0
    assert report.archive_malformed == 0
    assert report.healthy, "a directory named like a log is not "
    "the store's wound"


def test_binary_garbage_archive():
    store = _store()
    (store.directory / "webhook-log.jsonl").write_bytes(
        bytes(range(256)) * 4)
    report = _report(store)
    assert report.archive_rows == 0
    assert report.archive_malformed > 0, \
        "garbage lines are counted, not parsed"


def test_rotated_entry_is_a_directory_not_a_file():
    store = _store()
    archive = store.directory / "webhook-log.jsonl"
    archive.write_text(json.dumps(_row(0)) + "\n",
                       encoding="utf-8")
    archive.with_name(archive.name + ".1").mkdir()
    report = _report(store)
    assert report.archive_rows == 1
    assert report.archive_rotated == 1, \
        "presence is the finding; the doctor does not read it"


def test_every_row_lies_about_its_shape():
    rows = ["[]", '"a string"', "7", "null",
            json.dumps({"verified": "yes", "kind": ["x"]})]
    store = _store()
    (store.directory / "webhook-log.jsonl").write_text(
        "\n".join(rows) + "\n", encoding="utf-8")
    report = _report(store)
    assert report.archive_rows == 1, \
        "the /stats contract: rows are JSON objects"
    assert report.archive_malformed == 4, \
        "non-object lines are malformed, never guessed at"


def test_the_store_stays_healthy_through_all_of_it():
    for poison in ("dir", "binary", "lies"):
        store = _store()
        archive = store.directory / "webhook-log.jsonl"
        if poison == "dir":
            archive.mkdir()
        elif poison == "binary":
            archive.write_bytes(b"\x00\xff" * 64)
        else:
            archive.write_text("garbage\nlines\n", encoding="utf-8")
        assert _report(store).healthy, poison


def _row(i):
    return {"received_at": float(i), "verified": True,
            "kind": "k", "payload": {}}
