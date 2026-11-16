"""v572: the fleet memory names its conflicts.

The v5.7.0 dedupe kept the first store's copy and dropped the
rest SILENTLY — but two boxes holding DIFFERENT content under one
trace id is exactly the sync-conflict the ledger exists to catch:
a sync tool (or an attacker) rolling one store back reads as one
clean memory when the other box still holds the newer history.
The fleet view now counts every duplicate it reads again and
names the ids that DIVERGED (byte-different records under the
same id); the timeline, search and summary payloads carry it,
every CLI door prints the note once after its answer, and the
--export diary gains a conflicts line. Identical copies stay one
memory, no note. Single-store doors never grow the key.
"""

import json
import subprocess
import sys
from pathlib import Path

from approximately.recall import MultiStore
from approximately.store import TraceStore

ROOT = Path(__file__).resolve().parent.parent


def _run(*args):
    return subprocess.run(
        [sys.executable, "-m", "approximately", *args],
        capture_output=True, text=True, cwd=str(ROOT))


def _convo(tmp_path, name, task, *, result="ok"):
    store = TraceStore(tmp_path / name)
    from approximately.recorder import Recorder

    rec = Recorder(task, model="m/1", store=store, save=False)
    rec.tool("deploy", {"env": name}, result=result)
    rec.respond("done", success=True)
    store.save(rec.trace)
    return store


def _identical(tmp_path):
    a = _convo(tmp_path, "box-a", "ship the web service")
    b = TraceStore(tmp_path / "box-b")
    dup = TraceStore(tmp_path / "box-a").list_traces()[0]
    b.save(dup)
    return a, b


def test_identical_copies_stay_one_memory_without_a_note(tmp_path):
    _identical(tmp_path)
    view = MultiStore()
    view.add(TraceStore(tmp_path / "box-a"), str(tmp_path / "box-a"))
    view.add(TraceStore(tmp_path / "box-b"), str(tmp_path / "box-b"))
    assert len(view.list_traces()) == 1
    assert view.seen_again == 1
    assert view.diverged == [], \
        "a byte-identical copy is one memory, not a conflict"


def test_diverged_ids_are_named_not_swallowed(tmp_path):
    _convo(tmp_path, "box-a", "ship the web service", result="v1")
    store_a = TraceStore(tmp_path / "box-a")
    store_b = TraceStore(tmp_path / "box-b")
    dup = store_a.list_traces()[0]
    dup.steps[0].result = "v2-edited-elsewhere"
    store_b.save(dup)
    view = MultiStore()
    view.add(store_a, str(tmp_path / "box-a"))
    view.add(store_b, str(tmp_path / "box-b"))
    traces = view.list_traces()
    assert len(traces) == 1, \
        "the fleet still reads one memory per conversation"
    assert view.seen_again == 1
    assert view.diverged == [dup.id], (
        "two boxes holding two histories of one conversation is "
        "the sync-conflict the ledger exists to catch - keeping "
        "one side silently would read the conflict away")
    assert traces[0].store == "box-a", "the first store still wins"


def test_the_payloads_carry_the_counts(tmp_path):
    _convo(tmp_path, "box-a", "ship the web service", result="v1")
    store_a = TraceStore(tmp_path / "box-a")
    store_b = TraceStore(tmp_path / "box-b")
    dup = store_a.list_traces()[0]
    dup.steps[0].result = "v2-edited-elsewhere"
    store_b.save(dup)
    from approximately.recall import summarize, timeline

    view = MultiStore()
    view.add(store_a, str(tmp_path / "box-a"))
    view.add(store_b, str(tmp_path / "box-b"))
    view.list_traces()
    for payload in (timeline(view), summarize(view)):
        assert payload["duplicates"]["seen_again"] == 1, \
            "the JSON carries what the prose would hide"
        assert payload["duplicates"]["diverged"] == [dup.id]


def test_the_cli_prints_the_note_once(tmp_path):
    _convo(tmp_path, "box-a", "ship the web service", result="v1")
    store_a = TraceStore(tmp_path / "box-a")
    store_b = TraceStore(tmp_path / "box-b")
    dup = store_a.list_traces()[0]
    dup.steps[0].result = "v2-edited-elsewhere"
    store_b.save(dup)
    r = _run("recall", str(tmp_path / "box-a"),
             str(tmp_path / "box-b"))
    assert r.returncode == 0, r.stderr
    notes = [ln for ln in r.stdout.splitlines()
             if ln.startswith("note:")]
    assert len(notes) == 1, \
        "the conflict note is one line after the answer"
    assert "DIVERGED" in notes[0] and dup.id in notes[0]


def test_the_search_and_summary_doors_note_it_too(tmp_path):
    _convo(tmp_path, "box-a", "ship the web service", result="v1")
    store_a = TraceStore(tmp_path / "box-a")
    store_b = TraceStore(tmp_path / "box-b")
    dup = store_a.list_traces()[0]
    dup.steps[0].result = "v2-edited-elsewhere"
    store_b.save(dup)
    r = _run("recall", str(tmp_path / "box-a"),
             str(tmp_path / "box-b"), "--grep", "web")
    assert "DIVERGED" in r.stdout
    r2 = _run("recall-summary", str(tmp_path / "box-a"),
              str(tmp_path / "box-b"))
    assert "DIVERGED" in r2.stdout


def test_identical_copies_print_nothing(tmp_path):
    _identical(tmp_path)
    r = _run("recall", str(tmp_path / "box-a"),
             str(tmp_path / "box-b"), "--json")
    payload = json.loads(r.stdout)
    assert "duplicates" not in payload, (
        "one identical memory needs no conflict machinery in its "
        "shape")
    r2 = _run("recall", str(tmp_path / "box-a"),
              str(tmp_path / "box-b"))
    assert "note:" not in r2.stdout


def test_the_diary_gains_the_conflicts_line(tmp_path):
    _convo(tmp_path, "box-a", "ship the web service", result="v1")
    store_a = TraceStore(tmp_path / "box-a")
    store_b = TraceStore(tmp_path / "box-b")
    dup = store_a.list_traces()[0]
    dup.steps[0].result = "v2-edited-elsewhere"
    store_b.save(dup)
    out = tmp_path / "diary.md"
    r = _run("recall", str(tmp_path / "box-a"),
             str(tmp_path / "box-b"), "--export", str(out))
    assert r.returncode == 0, r.stderr
    text = out.read_text(encoding="utf-8")
    assert "DIVERGED" in text, \
        "a diary of a conflicted fleet must carry the conflict"


def test_a_single_store_never_grows_the_key(tmp_path):
    _convo(tmp_path, "box-a", "the only one")
    r = _run("recall", "--store", str(tmp_path / "box-a"), "--json")
    payload = json.loads(r.stdout)
    assert "duplicates" not in payload
