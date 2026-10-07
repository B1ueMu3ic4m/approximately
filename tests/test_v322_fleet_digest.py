"""v322: the fleet digest — the brief at fleet scale.

One store's brief became the night's habit; a fleet of stores reads
one page. ``digest --stores a b c`` keeps the week section
fleet-level (the digest dir's day-rows), gives every store its own
grades/owed/arrivals rollup, and ranks the sections worst-first so
the reader starts where it hurts. The redaction and delivery rules
travel unchanged: --redact and --post hold at fleet scale too.
"""

import argparse
import contextlib
import io
import tempfile
from pathlib import Path

from approximately.cli import cmd_digest
from approximately.digest import build_fleet_digest, render_fleet_markdown
from approximately.store import TraceStore
from approximately.trace import Step, Trace


def _store(task_fail, oks=2):
    store = TraceStore(tempfile.mkdtemp())
    t = Trace(task=task_fail, model="m")
    t.add(Step(kind="tool_call", tool="sh", result="x", tokens=5))
    t.success = False
    store.save(t)
    for i in range(oks):
        t = Trace(task=f"ok {i}", model="m")
        t.add(Step(kind="tool_call", tool="sh", result="x",
                   tokens=5))
        t.success = True
        store.save(t)
    return store


def _args(**kw):
    base = {"store": ".", "digest_dir": None, "triage_top": 3,
            "grade_floor": None, "json": False, "out": None,
            "post": None, "redact": False, "stores": None}
    base.update(kw)
    return argparse.Namespace(**base)


def test_fleet_digest_ranks_worst_first():
    calm = _store("calm failure")
    loud = _store("loud failure", oks=0)
    payload = build_fleet_digest([calm, loud])
    names = [b["store_name"] for b in payload["stores"]]
    assert payload["kind"] == "fleet_digest"
    assert names[0] == Path(loud.directory).name, \
        "the store hurting most reads first"
    page = render_fleet_markdown(payload)
    assert page.startswith("# fleet digest — 2 store(s)")
    assert page.index(Path(loud.directory).name) \
        < page.index(Path(calm.directory).name)


def test_fleet_brief_sections_are_complete():
    store = _store("failure one")
    payload = build_fleet_digest([store])
    brief = payload["stores"][0]
    assert brief["grades"] or brief["briefs_due"] >= 1
    assert brief["arrivals"]["failed"] == 1


def test_cli_fleet_mode_renders_and_refuses_empty():
    a = _store("failure a")
    b = _store("failure b")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        assert cmd_digest(_args(stores=[a.directory,
                                        b.directory])) == 0
    page = buf.getvalue()
    assert page.count("## ") == 2  # no week header, 2 store sections
    assert "postmortems owed" in page
    empty = TraceStore(tempfile.mkdtemp())
    args = _args(stores=[a.directory, empty.directory])
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        assert cmd_digest(args) == 2
    assert "empty" in err.getvalue()

