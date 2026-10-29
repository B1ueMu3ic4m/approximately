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


def test_include_rotated_folds_the_previous_log_in():
    archive = _archive([_row(10, kind="k"), _row(11, kind="k")])
    rotated = Path(str(archive) + ".1")
    with rotated.open("a", encoding="utf-8") as fh:
        for i in range(3):
            fh.write(json.dumps(_row(i, kind="k"),
                                sort_keys=True) + "\n")
    payload = read_archive(archive, limit=20)
    assert [r["received_at"] for r in payload["recent"]] == \
        [10, 11], "without the flag, only the current log"
    payload = read_archive(archive, limit=20, include_rotated=True)
    assert [r["received_at"] for r in payload["recent"]] == \
        [0, 1, 2, 10, 11], "the previous log comes first"
    assert payload["rows_total"] == 2, \
        "rows_total keeps meaning the current archive"


def test_since_keeps_only_rows_at_or_after_the_epoch():
    archive = _archive([_row(i) for i in range(5)])
    payload = read_archive(archive, since=3.0)
    assert [r["received_at"] for r in payload["recent"]] == \
        [3.0, 4.0]
    import pytest

    with pytest.raises(ValueError, match="unix timestamp"):
        read_archive(archive, since="not a number"), \
            "a hostile since is a refusal, not a crash"


def test_since_drops_rows_that_lie_about_their_stamp():
    archive = _archive([_row(1), dict(_row(2), received_at="x")])
    payload = read_archive(archive, since=0.5)
    assert [r["received_at"] for r in payload["recent"]] == [1], \
        "an unstampable row is not time travel"


def test_limit_zero_means_none_not_everything():
    archive = _archive([_row(i) for i in range(5)])
    payload = read_archive(archive, limit=0)
    assert payload["recent"] == [], ("rows[-0:] is the whole "
        "list - a slice quirk must not turn 'show none' into "
        "'show everything'")
    assert payload["rows_total"] == 5
