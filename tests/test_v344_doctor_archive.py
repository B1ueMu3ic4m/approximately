"""v344: doctor reads the receiver's archive too.

The webhook log lived beside the traces without ever getting a
checkup. Doctor now reports its rows, malformed lines (counted,
never guessed at — the same numbers /stats answers) and whether a
rotated previous log sits beside it. Read-only: the archive is
delivery evidence, housekeeping never touches it.
"""

import json
import tempfile
from pathlib import Path

from approximately.doctor import doctor
from approximately.store import TraceStore


def _store_with_archive(rows, rotated=None):
    store = TraceStore(tempfile.mkdtemp())
    archive = store.directory / "webhook-log.jsonl"
    with archive.open("a", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
    if rotated is not None:
        aside = Path(str(archive) + ".1")
        with aside.open("a", encoding="utf-8") as fh:
            for row in rotated:
                fh.write(json.dumps(row, sort_keys=True) + "\n")
    return store


def _row(i, verified=True):
    return {"received_at": float(i), "verified": verified,
            "kind": "k", "payload": {}}


def test_archive_counts_land_in_the_report():
    store = _store_with_archive([_row(0), "not json", _row(2)])
    report = doctor(store.directory)
    assert report.archive_rows == 2
    assert report.archive_malformed == 1
    assert report.archive_rotated == 0
    assert report.healthy, "a malformed line is a note, not a wound"


def test_rotated_log_is_reported_present():
    store = _store_with_archive([_row(9)], rotated=[_row(0)])
    report = doctor(store.directory)
    assert report.archive_rotated == 1


def test_no_archive_is_no_finding():
    store = TraceStore(tempfile.mkdtemp())
    report = doctor(store.directory)
    assert report.archive_rows == 0
    assert report.archive_malformed == 0
    assert report.archive_rotated == 0


def test_the_json_and_prose_shapes_carry_it():
    import argparse
    import contextlib
    import io

    from approximately.cli import cmd_doctor

    store = _store_with_archive([_row(0)], rotated=[_row(1)])
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        cmd_doctor(argparse.Namespace(
            store=str(store.directory), digest_dir=None,
            judge_cache=None, spool=None, deep=False, fix=False,
            json=True))
    payload = json.loads(buf.getvalue())
    assert payload["archive_rows"] == 1
    assert payload["archive_rotated"] == 1
