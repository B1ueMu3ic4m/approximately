"""v371: the inbox is searchable.

The archive answered "how many" and "which kinds" but not
"which rows mention deploy" — the on-call scrolled the tail by
eye. ``read_archive`` gains ``contains`` (case-insensitive
substring over the row's own JSON), the ``received`` door gains
``--grep`` and a ``--since`` that speaks human durations
(``30m``, ``2h``, ``1d``), and the MCP inbox tool narrows the
view the same way. One reader, every surface, now searchable.
"""

import argparse
import contextlib
import io
import json
import tempfile
import time

import pytest

from approximately.cli import _parse_since, cmd_received
from approximately.mcp_server import ServerContext, _tool_inbox
from approximately.receiver import read_archive, row_passes
from approximately.store import TraceStore


def _store_with_archive():
    store = TraceStore(tempfile.mkdtemp())
    archive = store.directory / "webhook-log.jsonl"
    now = time.time()
    rows = [{"received_at": now - 50, "verified": True,
             "kind": "trace_failure",
             "payload": {"cmd": "deploy prod"}},
            {"received_at": now - 100, "verified": False,
             "kind": "spool", "payload": {"cmd": "rollback"}},
            {"received_at": now - 300, "verified": True,
             "kind": "trace_failure", "payload": {"cmd": "test"}}]
    with archive.open("a", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
        fh.write("garbage line\n")
    return store, archive


def test_contains_filters_over_the_rows_own_json():
    _store, archive = _store_with_archive()
    hits = read_archive(archive, contains="deploy")
    assert [r["kind"] for r in hits["recent"]] == ["trace_failure"]
    assert hits["rows_total"] == 3, \
        "the census stays the archive's; the view narrows"
    # case-insensitive: the row says "deploy", the caller says "DEPLOY"
    assert len(read_archive(archive,
                            contains="DEPLOY")["recent"]) == 1


def test_no_match_is_an_empty_view_not_an_error():
    _store, archive = _store_with_archive()
    payload = read_archive(archive, contains="nonexistent")
    assert payload["recent"] == []
    assert payload["rows_total"] == 3


def test_hostile_contains_is_refused_like_hostile_since():
    # the refusal lives at the reader boundary, exactly where a
    # hostile `since` is refused; the predicate stays arithmetic
    _store, archive = _store_with_archive()
    with pytest.raises(ValueError):
        read_archive(archive, contains=123)


def test_row_passes_searches_the_delivered_bytes():
    row = {"received_at": 1.0, "verified": True, "kind": "k",
           "payload": {"note": "Rotate the KEYS"}}
    assert row_passes(row, None, False, None, "keys")
    assert not row_passes(row, None, False, None, "delete")
    assert not row_passes(row, None, False, None, "KEYS1")
    assert row_passes(row, None, False, None, ""), \
        "the empty needle matches every row, as substrings do"


def test_grep_reaches_the_received_door():
    store, archive = _store_with_archive()
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        assert cmd_received(argparse.Namespace(
            store=str(store.directory), archive=str(archive),
            limit=20, kind=None, unverified_only=False,
            include_rotated=False, since=None, grep="rollback",
            json=True)) == 0
    payload = json.loads(buf.getvalue())
    assert [r["kind"] for r in payload["recent"]] == ["spool"]
    assert payload["rows_total"] == 3


def test_since_speaks_human_durations():
    now = time.time()
    assert _parse_since("1h") == pytest.approx(now - 3600.0,
                                               abs=5.0)
    assert _parse_since("30m") == pytest.approx(now - 1800.0,
                                                abs=5.0)
    assert _parse_since("1.5d") == pytest.approx(now - 129600.0,
                                                 abs=5.0)
    assert _parse_since("1w") == pytest.approx(now - 604800.0,
                                               abs=5.0)
    assert _parse_since("0s") == pytest.approx(now, abs=5.0)
    assert _parse_since("1793312531") == 1793312531.0, \
        "a raw epoch passes through untouched"


def test_since_refuses_garbage_at_the_flag_boundary():
    with pytest.raises(argparse.ArgumentTypeError) as err:
        _parse_since("yesterday")
    assert "30m" in str(err.value)
    with pytest.raises(argparse.ArgumentTypeError):
        _parse_since("-5x")
    with pytest.raises(argparse.ArgumentTypeError):
        _parse_since("2 parsecs")


def test_since_duration_filters_the_door():
    store, archive = _store_with_archive()
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        assert cmd_received(argparse.Namespace(
            store=str(store.directory), archive=str(archive),
            limit=20, kind=None, unverified_only=False,
            include_rotated=False, since=_parse_since("2m"),
            grep=None, json=True)) == 0
    payload = json.loads(buf.getvalue())
    assert [r["kind"] for r in payload["recent"]] == \
        ["trace_failure", "spool"], \
        "the 3-minute-old row falls out of a 2-minute window"


def test_mcp_inbox_narrows_like_the_cli():
    store, _archive = _store_with_archive()
    ctx = ServerContext(store.directory)
    hits = _tool_inbox(ctx, {"contains": "DEPLOY"})
    assert len(hits["recent"]) == 1
    by_kind = _tool_inbox(ctx, {"kind": "trace_failure"})
    assert len(by_kind["recent"]) == 2
    unverified = _tool_inbox(ctx, {"unverified_only": True})
    assert [r["kind"] for r in unverified["recent"]] == ["spool"]


def test_mcp_inbox_refuses_hostile_filter_types():
    store, _archive = _store_with_archive()
    ctx = ServerContext(store.directory)
    with pytest.raises(ValueError):
        _tool_inbox(ctx, {"contains": 123})
    with pytest.raises(ValueError):
        _tool_inbox(ctx, {"kind": ["trace_failure"]})
