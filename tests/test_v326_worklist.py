"""v326: the postmortem worklist — handoff --queue.

The digest counts what a shift owes; the worklist is the paying:
one page of briefs for the top of the triage queue (unannotated
failures first, the queue's own order). An unreadable trace becomes
its own one-line entry, never a torn page; an empty debt says so.
--redact holds, as everywhere the handoff speaks.
"""

import argparse
import contextlib
import io
import tempfile

from approximately.cli import cmd_handoff
from approximately.handoff import worklist
from approximately.store import TraceStore
from approximately.trace import Step, Trace


def _trace(store, task, agent="bot", tokens=5):
    t = Trace(task=task, model="m")
    t.add(Step(kind="tool_call", tool="sh", result="x", tokens=tokens,
               agent=agent))
    t.success = False
    store.save(t)
    return t


def _store(n=3):
    # descending tokens make the triage order deterministic:
    # near-identical failures may tie on Windows' coarse clock
    store = TraceStore(tempfile.mkdtemp())
    traces = [_trace(store, f"failure {i}",
                     tokens=100 - i * 30) for i in range(n)]
    ok = Trace(task="fine", model="m")
    ok.add(Step(kind="tool_call", tool="sh", result="x", tokens=5))
    ok.success = True
    store.save(ok)
    return store, traces


def test_worklist_renders_briefs_for_the_owed():
    store, traces = _store(3)
    page = worklist(store, limit=2)
    assert page.count("# Handoff:") == 2
    assert "postmortem worklist — 2 brief(s)" in page
    for t in traces[:2]:
        assert t.id in page


def test_empty_debt_says_so():
    store, traces = _store(1)
    store.annotate(traces[0].id, "postmortemed")
    page = worklist(store, limit=5)
    assert "nothing owed" in page


def test_poison_never_enters_the_worklist():
    # triage filters poison upstream; the queue only names readable
    # failures. (worklist keeps a defensive one-line branch for a
    # trace that vanishes between queueing and rendering.)
    store = TraceStore(tempfile.mkdtemp())
    _trace(store, "readable failure")
    (store.directory / "poison.json").write_text("{bad",
                                                 encoding="utf-8")
    page = worklist(store, limit=5)
    assert "unreadable" not in page
    assert page.count("# Handoff:") == 1  # the readable one only
    assert "poison" not in page


def test_cli_queue_and_refusal(capsys):
    store, _ = _store(2)
    args = argparse.Namespace(store=store.directory, trace=None,
                              queue=2, redact=False, out=None,
                              json=False)
    assert cmd_handoff(args) == 0
    assert "# Handoff:" in capsys.readouterr().out
    args.queue = None
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        assert cmd_handoff(args) == 2
    assert "--queue" in err.getvalue()


def test_redaction_holds_on_the_worklist():
    store = TraceStore(tempfile.mkdtemp())
    _trace(store, "hold AKIAIOSFODNN7EXAMPLE then fail")
    scrubbed = worklist(store, limit=1, table=None)  # unredacted
    assert "AKIAIOSFODNN7EXAMPLE" in scrubbed
    from approximately.redact import compile_patterns

    clean = worklist(store, limit=1, table=compile_patterns())
    assert "AKIAIOSFODNN7EXAMPLE" not in clean
    assert "[REDACTED:aws_key]" in clean
