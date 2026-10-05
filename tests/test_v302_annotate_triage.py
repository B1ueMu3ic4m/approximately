"""v302: the triage queue drafts its own annotations.

``annotate --from-triage`` drafts notes from the queue's top
unannotated failures — mode, score, novelty, tokens, agent count —
verdicts left empty for a human. Annotated failures never come back
(unannotated_only), and the drafted note lands in the same
append-only sidecar as every other annotation.
"""

import argparse
import contextlib
import io
import json

from approximately.cli import cmd_annotate
from approximately.store import TraceStore
from approximately.trace import Step, Trace


def _seed(tmp_path, failures=3, successes=2):
    store = TraceStore(tmp_path)
    for i in range(failures):
        t = Trace(task=f"fail {i}", model="m")
        t.add(Step(kind="tool_call", tool="sh", result="x",
                   error="boom", tokens=1000, agent=f"a{i}"))
        t.success = False
        store.save(t)
    for i in range(successes):
        t = Trace(task=f"ok {i}", model="m")
        t.add(Step(kind="tool_call", tool="sh", result="fine"))
        t.success = True
        store.save(t)
    return store


def _args(tmp_path, **extra):
    base = {"store": str(tmp_path), "trace": None, "note": None,
            "author": "", "verdict": "", "from_anomalies": False,
            "from_triage": False, "anomaly_count": 5,
            "json": True}
    base.update(extra)
    return argparse.Namespace(**base)


def test_drafts_top_of_queue(tmp_path):
    store = _seed(tmp_path)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        assert cmd_annotate(_args(tmp_path,
                                  **{"from_triage": True})) == 0
    payload = json.loads(buf.getvalue())
    assert payload["drafted"] == 3 and payload["queue"] == 3
    notes = store.annotations()
    assert len(notes) == 3
    assert all(n["verdict"] == "" for n in notes)
    assert all(n["note"].startswith("draft:") for n in notes)
    assert "novelty 1.00" in notes[0]["note"]
    assert "1,000 tokens" in notes[0]["note"]


def test_annotated_failures_never_return(tmp_path):
    store = _seed(tmp_path, failures=2)
    first = store.list_traces()[0]
    store.annotate(first.id, "human got here first",
                   verdict="confirmed")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        cmd_annotate(_args(tmp_path, **{"from_triage": True}))
    payload = json.loads(buf.getvalue())
    assert payload["drafted"] == 1 and payload["queue"] == 1
    drafts = [n for n in store.annotations()
              if n["note"].startswith("draft:")]
    assert len(drafts) == 1
    assert drafts[0]["trace_id"] != first.id


def test_cap_and_empty_queue(tmp_path):
    store = _seed(tmp_path, failures=4)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        cmd_annotate(_args(tmp_path, **{"from_triage": True,
                                        "anomaly_count": 2}))
    assert json.loads(buf.getvalue())["drafted"] == 2
    # the cap spares two: a second pass drafts the rest, then a
    # third drafts zero (everyone has a note now)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        cmd_annotate(_args(tmp_path, **{"from_triage": True}))
    assert json.loads(buf.getvalue())["drafted"] == 2
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        cmd_annotate(_args(tmp_path, **{"from_triage": True}))
    assert json.loads(buf.getvalue())["drafted"] == 0


def test_prose_form(tmp_path, capsys):
    _seed(tmp_path, failures=1)
    assert cmd_annotate(_args(tmp_path, **{"from_triage": True,
                                           "json": False})) == 0
    assert "drafted 1 note(s)" in capsys.readouterr().out


def test_success_only_store_drafts_zero(tmp_path):
    _seed(tmp_path, failures=0)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        cmd_annotate(_args(tmp_path, **{"from_triage": True}))
    assert json.loads(buf.getvalue())["drafted"] == 0
