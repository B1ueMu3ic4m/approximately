"""v342: `received` — the cron-friendly reader of the archive.

The archive was readable over HTTP (/stats) and through MCP
(inbox); the shell had only curl. The `received` door reads it
back with the same one-reader contract: the /stats shape plus the
most recent matching rows, newest last — filtered by kind or by
the open tap's unverified mark, rendered as prose or JSON.
"""

import json
import tempfile
from pathlib import Path

from approximately.cli import cmd_received
from approximately.receiver import read_archive


def _archive(rows):
    archive = Path(tempfile.mkdtemp()) / "webhook-log.jsonl"
    with archive.open("a", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
    return archive


def _row(i, kind="trace_failure", verified=True):
    return {"received_at": float(i), "verified": verified,
            "kind": kind, "payload": {"seq": i}}


def _args(archive, **kw):
    import argparse

    base = {"store": str(archive.parent), "archive": str(archive),
            "limit": 20, "kind": None, "unverified_only": False,
            "json": False}
    base.update(kw)
    return argparse.Namespace(**base)


def test_prose_shape_counts_and_rows(capsys):
    archive = _archive([_row(i) for i in range(30)])
    assert cmd_received(_args(archive, limit=3)) == 0
    out = capsys.readouterr().out
    assert "30 rows (30 verified, 0 unverified, 0 malformed)" in out
    assert "trace_failure: 30" in out
    assert out.count("  2") >= 1  # recent rows carry their stamps


def test_json_shape_matches_the_stats_contract():
    archive = _archive([_row(i, verified=(i % 2 == 0))
                        for i in range(6)])
    import contextlib
    import io

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        assert cmd_received(_args(archive, json=True)) == 0
    payload = json.loads(buf.getvalue())
    assert payload["rows"] == 6 and payload["verified"] == 3
    assert payload["rows_total"] == 6
    assert len(payload["recent"]) == 6
    assert payload["recent"][-1]["payload"]["seq"] == 5


def test_kind_filter_keeps_the_tail_of_that_kind():
    archive = _archive([_row(i, kind=f"k{i % 3}")
                        for i in range(9)])
    payload = read_archive(archive, limit=2, kind="k1")
    assert payload["rows"] == 9
    assert [r["received_at"] for r in payload["recent"]] == [4, 7]


def test_unverified_only_surfaces_open_tap_rows():
    archive = _archive([_row(0, verified=True),
                        _row(1, verified=False),
                        _row(2, verified=False)])
    payload = read_archive(archive, unverified_only=True)
    assert [r["received_at"] for r in payload["recent"]] == [1, 2]


def test_missing_archive_is_zeros_not_an_error(capsys):
    archive = Path(tempfile.mkdtemp()) / "absent.jsonl"
    assert cmd_received(_args(archive)) == 0
    out = capsys.readouterr().out
    assert "0 rows" in out
