"""v324: the arrival window — digest --since-days.

The brief read "today" only; Monday mornings need the weekend.
``--since-days N`` widens the arrival window (labels say so), and
the window is honest about what it counts — an old failure outside
the window stays invisible to arrivals but never to triage (the
queue's clock is its own).
"""

import argparse
import contextlib
import io
import tempfile
import time

from approximately.cli import cmd_digest
from approximately.digest import build_digest, render_markdown
from approximately.mcp_server import ServerContext, _tool_digest
from approximately.store import TraceStore
from approximately.trace import Step, Trace


def _trace(store, task, success, age_days):
    t = Trace(task=task, model="m")
    t.add(Step(kind="tool_call", tool="sh", result="x", tokens=5))
    t.success = success
    t.created_at = time.time() - age_days * 86400.0
    store.save(t)
    return t


def _store():
    # ages are computed from local midnight so the calendar windows
    # hold at any wall-clock hour (the suite runs at night too)
    import datetime as dt

    midnight = dt.datetime.combine(dt.date.today(),
                                   dt.time.min).timestamp()
    now = time.time()
    into_today = max(60.0, (now - midnight) / 2)
    store = TraceStore(tempfile.mkdtemp())
    _trace(store, "today failure", False, into_today / 86400.0)
    _trace(store, "yesterday ok", True,
           (into_today + 43200) / 86400.0)
    _trace(store, "weekend failure", False,
           (into_today + 3 * 86400) / 86400.0)
    return store


def test_default_window_is_today_only():
    payload = build_digest(_store())
    assert payload["arrivals"]["failed"] == 1
    assert payload["arrivals"]["window_days"] == 1


def test_widened_window_reads_the_weekend():
    payload = build_digest(_store(), since_days=7)
    assert payload["arrivals"]["failed"] == 2
    assert payload["arrivals"]["ok"] == 1
    assert payload["arrivals"]["window_days"] == 7
    page = render_markdown(payload)
    assert "in the last 7 day(s)" in page


def test_triage_queue_keeps_its_own_clock():
    # the weekend failure is outside today's arrivals but in the queue
    payload = build_digest(_store())
    assert payload["arrivals"]["failed"] == 1
    assert len(payload["triage"]) == 2


def test_cli_and_mcp_carry_the_flag():
    store = _store()
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        assert cmd_digest(argparse.Namespace(
            store=store.directory, digest_dir=None, triage_top=5,
            grade_floor=None, since_days=7, json=False, out=None,
            post=None, redact=False)) == 0
    assert "last 7 day(s)" in buf.getvalue()
    payload = _tool_digest(ServerContext(store.directory),
                           {"since_days": 7})
    assert payload["arrivals"]["window_days"] == 7
    assert payload["arrivals"]["failed"] == 2
