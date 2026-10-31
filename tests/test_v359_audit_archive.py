"""v359: the audit carries the archive checkup.

doctor CLI reports the receiver's archive (v3.45.0); the audit's
JSON and junit renderings did not. The doctor section now carries
archive_rows / archive_malformed / archive_rotated when an
archive exists — counted, never verdict-flipping (the archive is
delivery evidence) — and the junit doctor message names a
malformed count so a torn log is visible in CI output.
"""

import argparse
import contextlib
import io
import json
import tempfile

from approximately.cli import cmd_audit
from approximately.mcp_server import ServerContext, _tool_audit
from approximately.store import TraceStore


def _store_with_archive():
    from approximately.recorder import Recorder

    store = TraceStore(tempfile.mkdtemp())
    rec = Recorder("kept run", store=store)
    rec.tool("sh", {}, result="ok")
    rec.respond("done", success=True)
    store.save(rec.trace)
    archive = store.directory / "webhook-log.jsonl"
    with archive.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"received_at": 1.0, "verified": True,
                             "kind": "k", "payload": {}}) + "\n")
        fh.write("garbage\n")
    return store


def test_audit_json_carries_the_archive():
    store = _store_with_archive()
    rep = _tool_audit(ServerContext(str(store.directory)),
                      {"digest_dir": None, "week_compare": False})
    doctor = rep["doctor"]
    assert doctor["archive_rows"] == 1
    assert doctor["archive_malformed"] == 1
    assert rep["ok"] is True, "a torn line is a note, not a wound"


def test_no_archive_adds_no_fields():
    from approximately.recorder import Recorder

    store = TraceStore(tempfile.mkdtemp())
    rec = Recorder("clean run", store=store)
    rec.tool("sh", {}, result="ok")
    rec.respond("done", success=True)
    store.save(rec.trace)
    rep = _tool_audit(ServerContext(str(store.directory)),
                      {"digest_dir": None, "week_compare": False})
    assert "archive_rows" not in rep["doctor"]


def test_junit_names_a_malformed_count():
    store = _store_with_archive()
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        assert cmd_audit(argparse.Namespace(
            store=str(store.directory), digest_dir=None,
            spend_ceiling=None, failure_budget=None, deep=False,
            fix=False, fail_on_worsening=False, prices=None,
            since=None, max_failure_rate=None, max_tokens=None,
            max_budget_breaches=None, max_result_chars=None,
            max_latency_ms=None, max_repeated_actions=None,
            max_steps=None, grade_floor=None, triage_top=None,
            week_compare=False, format="junit", json=False)) == 0
    out = buf.getvalue()
    assert 'name="doctor"' in out
    assert "archive_malformed=1" in out
