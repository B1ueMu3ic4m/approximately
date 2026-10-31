"""v356: `received --follow` — the on-call terminal's live view.

The archive had readers; it had no follower. `follow_archive`
yields rows as they land, offset-tracked — a rotation (the file
shrinking under the reader) restarts from zero, so nothing is
skipped twice or lost. Malformed lines are skipped; they were
counted at read time. `--max-passes` bounds the loop for tests.
"""

import json
import tempfile
import threading
import time
from pathlib import Path

from approximately.receiver import follow_archive


def _row(i, verified=True):
    return {"received_at": float(i), "verified": verified,
            "kind": "spool", "payload": {"seq": i}}


def test_rows_arrive_as_they_land():
    archive = Path(tempfile.mkdtemp()) / "webhook-log.jsonl"

    def writer():
        time.sleep(0.05)
        for i in range(3):
            with archive.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(_row(i)) + "\n")
            time.sleep(0.15)

    thread = threading.Thread(target=writer)
    thread.start()
    seen = [row["payload"]["seq"] for row in
            follow_archive(archive, interval=0.05, max_passes=30)]
    thread.join()
    assert seen == [0, 1, 2]


def test_rotation_restarts_from_zero_without_loss():
    archive = Path(tempfile.mkdtemp()) / "webhook-log.jsonl"

    def writer():
        time.sleep(0.05)
        with archive.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(_row(0)) + "\n")
        time.sleep(0.3)
        # rotate: the current log moves aside, a fresh one starts
        archive.replace(archive.with_name(archive.name + ".1"))
        with archive.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(_row(7)) + "\n")

    threading.Thread(target=writer).start()
    seen = [row["payload"]["seq"] for row in
            follow_archive(archive, interval=0.05, max_passes=20)]
    assert seen == [0, 7], f"no doubles, no skips: {seen}"


def test_malformed_lines_are_skipped_silently():
    archive = Path(tempfile.mkdtemp()) / "webhook-log.jsonl"
    with archive.open("a", encoding="utf-8") as fh:
        fh.write("garbage\n")
        fh.write(json.dumps(_row(1)) + "\n")
    seen = [row["payload"]["seq"] for row in
            follow_archive(archive, interval=0.05, max_passes=2)]
    assert seen == [1]


def test_missing_archive_waits_patiently():
    archive = Path(tempfile.mkdtemp()) / "absent.jsonl"

    def writer():
        time.sleep(0.1)
        archive.write_text(json.dumps(_row(9)) + "\n")

    threading.Thread(target=writer).start()
    seen = [row["payload"]["seq"] for row in
            follow_archive(archive, interval=0.05, max_passes=10)]
    assert seen == [9]


def test_follow_json_emits_one_object_per_row(capsys):
    import json as _json

    archive = Path(tempfile.mkdtemp()) / "webhook-log.jsonl"
    with archive.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(_row(1)) + "\n")
        fh.write("garbage\n")
        fh.write(json.dumps(_row(2)) + "\n")
    import argparse

    from approximately.cli import cmd_received

    assert cmd_received(argparse.Namespace(
        store=str(archive.parent), archive=str(archive), limit=20,
        kind=None, unverified_only=False, include_rotated=False,
        since=None, json=True, follow=True, interval=0.05,
        max_passes=2)) == 0
    lines = [line for line in capsys.readouterr().out.splitlines()
             if line]
    rows = [_json.loads(line) for line in lines]
    assert [r["payload"]["seq"] for r in rows] == [1, 2], \
        "one machine-readable object per row, poison skipped"
