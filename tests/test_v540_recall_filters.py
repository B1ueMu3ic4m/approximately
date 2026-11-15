"""v540: recall answers the follow-up questions.

"Which of those conversations FAILED?" and "the gpt-4o ones" and
"give me the memory as a file" — the filters the memory doors
were missing, plus the audit runner-ups: a fleet dashboard over a
typo'd store used to be silently created and report a healthy 0%,
and a nan --floor made every mutation qualify as non-material.
"""

import json
import subprocess
import sys
import time
from pathlib import Path

from approximately.diff import diff as trace_diff
from approximately.diff import first_fault
from approximately.recall import export_diary, summarize, timeline
from approximately.store import TraceStore
from approximately.trace import Step, Trace

ROOT = Path(__file__).resolve().parent.parent
NOW = time.time()


def _store(tmp_path):
    from approximately.recorder import Recorder

    store = TraceStore(tmp_path)
    rows = [
        ("deploy the retry fix", True, "gpt-4o", 3600),
        ("migrate the database", False, "gpt-4o", 1800),
        ("design the new schema", True, "claude-3", 900),
    ]
    for _i, (task, ok, model, age) in enumerate(rows):
        rec = Recorder(task, store=store, save=False)
        rec.trace.created_at = NOW - age
        rec.trace.model = model
        rec.tool("sh", {"cmd": "x"}, result="ok" if ok else "boom")
        rec.respond("done" if ok else "gave up", success=ok)
        store.save(rec.trace, stamp=False)
    return store


def _run(*args, store):
    from approximately.store import TraceStore

    path = store.directory if isinstance(store, TraceStore) \
        else store
    return subprocess.run(
        [sys.executable, "-m", "approximately", "--store",
         str(path), *args],
        capture_output=True, text=True, cwd=str(ROOT))


def test_the_model_filter_narrows_the_memory(tmp_path):
    store = _store(tmp_path)
    payload = timeline(store, model="gpt-4o")
    assert payload["conversations"] == 2
    assert all("gpt-4o" in e["model"] for e in
               [entry for day in payload["days"]
                for entry in day["entries"]])
    assert timeline(store, model="claude")["conversations"] == 1, \
        "substring, case-insensitive"


def test_the_outcome_filters_split_success_from_failure(tmp_path):
    store = _store(tmp_path)
    assert timeline(store, outcomes="failed")["conversations"] == 1
    assert timeline(store, outcomes="ok")["conversations"] == 2
    summary = summarize(store, outcomes="failed")
    assert summary["failed"] == 1 and summary["conversations"] == 1, \
        "the failed-only summary is the postmortem reading list"


def test_the_summary_door_carries_the_filters(tmp_path):
    store = _store(tmp_path)
    r = _run("recall-summary", "--model", "claude",
             "--failed-only", store=store)
    assert r.returncode == 0
    assert "design the new schema" not in r.stdout,  (
        "a successful claude conversation stays out of a  "
        "failed-only claude summary")
    r2 = _run("recall", "--failed-only", "--json", store=store)
    data = json.loads(r2.stdout)
    assert data["conversations"] == 1


def test_the_diary_export_writes_one_markdown_file(tmp_path):
    store = _store(tmp_path)
    out = tmp_path / "diary.md"
    report = export_diary(store, out)
    assert report["conversations"] == 3
    text = out.read_text(encoding="utf-8")
    assert "# Conversation diary" in text
    assert "Top topics" in text and "## Timeline" in text
    assert "migrate the database" in text
    leftovers = [p.name for p in tmp_path.iterdir()
                 if p.name.endswith(".tmp")]
    assert not leftovers, "atomic write: no half diary"


def test_the_export_door_refuses_a_missing_directory(tmp_path):
    store = _store(tmp_path)
    r = _run("recall", "--export",
             str(tmp_path / "nope" / "diary.md"), store=store)
    assert r.returncode == 2 and "not found" in r.stderr


def test_the_recall_door_exports_the_diary(tmp_path):
    store = _store(tmp_path)
    out = tmp_path / "diary.md"
    r = _run("recall", "--export", str(out), store=store)
    assert r.returncode == 0 and "diary written" in r.stdout
    assert "# Conversation diary" in out.read_text(encoding="utf-8")


def test_a_fleet_dashboard_over_a_typo_store_is_a_refusal(tmp_path):
    r = _run("fleet", str(tmp_path / "typo-store"),
             str(tmp_path / "other"), store=tmp_path)
    assert r.returncode == 2,  (
        "a fleet dashboard that reads 'all healthy' over stores  "
        "that do not exist used to be silently created")
    assert "store not found" in r.stderr
    assert not (tmp_path / "typo-store").exists()


def test_a_fleet_trend_keeps_its_placeholder_stores(tmp_path):
    digests = tmp_path / "digests"
    digests.mkdir()
    r = _run("fleet", str(tmp_path / "unused"), "--trend",
             "--digest-dir", str(digests), store=tmp_path)
    assert r.returncode == 0,  (
        "the trend reads the digest directory; the store slots  "
        "are placeholders there")


def test_a_nan_floor_cannot_silence_every_mutation(tmp_path):
    from approximately.recorder import Recorder

    store = TraceStore(tmp_path)
    rec = Recorder("nan floor", store=store)
    rec.tool("deploy", {"i": 1}, result="ok")
    rec.respond("done", success=True)
    store.save(rec.trace)
    other = TraceStore(tmp_path / "other")
    rec2 = Recorder("nan floor 2", store=other)
    rec2.tool("deploy", {"i": 2}, result="CHANGED RESULT")
    rec2.respond("done", success=True)
    other.save(rec2.trace)
    r = _run("bisect", rec.trace.id, "--other", rec2.trace.id,
             "--other-store", str(other.directory), "--floor",
             "nan", store=store)
    assert r.returncode == 2,  (
        "nan compares False against everything: every mutation  "
        "would silently qualify as non-material")


def test_first_fault_still_honors_a_real_floor(tmp_path):
    a = Trace(task="a", created_at=1.0)
    a.add(Step(kind="tool_call", tool="x", args={"i": 1},
               result="same"))
    b = Trace(task="b", created_at=1.0)
    b.add(Step(kind="tool_call", tool="x", args={"i": 2},
               result="CHANGED"))
    td = trace_diff(a, b)
    assert first_fault(td, floor=0.8) is not None
    assert first_fault(td, floor=1.01) is not None,  (
        "the docstring contract: floor 1.01 makes any non-equal  "
        "entry qualify")
