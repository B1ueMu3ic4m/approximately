"""v5941: the diary carries the triage words.

The diary is the artifact a person opens months later — and the
part a reader actually came for is the triage verdict ("was this
the one we confirmed?"). ``recall --export`` now appends each
conversation's latest verdict and a bounded note excerpt to its
timeline line (``· triage: confirmed "looks like…"``), read from
the annotation sidecar in ONE pass, across the fleet view too
(each box's verdict rides its own entries). The stdout timeline
stays lean — the door that answers "what did I talk about" does
not grow store lookups per line — and a store without annotations
renders without a triage tail at all.
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _run(*args):
    return subprocess.run(
        [sys.executable, "-m", "approximately", *args],
        capture_output=True, text=True, cwd=str(ROOT),
        encoding="utf-8")


def _seed(tmp_path):
    from approximately.recorder import Recorder
    from approximately.store import TraceStore

    store = TraceStore(tmp_path / "s")
    rec = Recorder("annotated failure run", save=False)
    rec.tool("deploy", {}, result=None, error="boom")
    rec.respond("done", success=False)
    store.save(rec.trace)
    rec2 = Recorder("plain ok run", save=False)
    rec2.tool("ls", {}, result="ok")
    rec2.respond("done", success=True)
    store.save(rec2.trace)
    store.annotate(rec.trace.id,
                   "looks like the deploy timeout family",
                   verdict="confirmed")
    return store


def test_the_diary_lines_carry_their_verdict(tmp_path):
    store = _seed(tmp_path)
    out = tmp_path / "diary.md"
    r = _run("--store", str(store.directory), "recall", "--export",
             str(out))
    assert r.returncode == 0, r.stderr
    text = out.read_text(encoding="utf-8")
    tails = [line for line in text.splitlines()
             if "· triage:" in line]
    assert len(tails) == 1, \
        "exactly the annotated conversation carries a triage tail"
    assert ('triage: confirmed "looks like the deploy timeout '
            'family"') in tails[0]
    assert not [line for line in text.splitlines()
                if "plain ok run" in line and "· triage" in line], \
        "an unannotated conversation has no triage tail"


def test_the_stdout_timeline_stays_lean(tmp_path):
    store = _seed(tmp_path)
    r = _run("--store", str(store.directory), "recall")
    assert r.returncode == 0, r.stderr
    assert "· triage:" not in r.stdout, (
        "the door that answers 'what did I talk about' does not "
        "grow store lookups per line")


def test_a_store_without_annotations_renders_clean(tmp_path):
    from approximately.recorder import Recorder
    from approximately.store import TraceStore

    store = TraceStore(tmp_path / "s2")
    rec = Recorder("no triage run", save=False)
    rec.tool("ls", {}, result="ok")
    rec.respond("done", success=True)
    store.save(rec.trace)
    out = tmp_path / "d2.md"
    r = _run("--store", str(store.directory), "recall", "--export",
             str(out))
    assert r.returncode == 0, r.stderr
    assert "triage:" not in out.read_text(encoding="utf-8")


def test_the_fleet_diary_rides_each_box(tmp_path):
    from approximately.recorder import Recorder
    from approximately.store import TraceStore

    for name, task in (("a", "box a run"), ("b", "box b run")):
        store = TraceStore(tmp_path / name)
        rec = Recorder(task, save=False)
        rec.tool("deploy", {}, result="ok")
        rec.respond("done", success=True)
        store.save(rec.trace)
    box_b = TraceStore(tmp_path / "b")
    box_b.annotate(box_b.list_traces()[0].id, "box b note",
                   verdict="false-positive")
    out = tmp_path / "fleet.md"
    r = _run("recall", "--export", str(out), str(tmp_path / "a"),
             str(tmp_path / "b"))
    assert r.returncode == 0, r.stderr
    tails = [line for line in out.read_text(encoding="utf-8")
             .splitlines() if "· triage:" in line]
    assert len(tails) == 1, "box b's verdict rides its own entry"
    assert "false-positive" in tails[0] and "{b}" in tails[0]


def test_the_latest_verdict_wins_and_lines_stay_bounded(tmp_path):
    store = _seed(tmp_path)
    tid = store.list_traces()[0].id
    store.annotate(tid, "superseded note", verdict="confirmed")
    store.annotate(tid, "final word after more digging",
                   verdict="false-positive")
    out = tmp_path / "diary.md"
    r = _run("--store", str(store.directory), "recall", "--export",
             str(out))
    assert r.returncode == 0, r.stderr
    tails = [line for line in out.read_text(encoding="utf-8")
             .splitlines() if "· triage:" in line]
    assert len(tails) == 1, "one conversation, one triage tail"
    assert "false-positive" in tails[0] and \
        "final word after more digging" in tails[0], \
        "the LATEST annotation is what the reader gets"
    assert all(len(line) < 200 for line in tails), \
        "the excerpt is bounded: the line stays one line"
