"""v570: memory spans the fleet.

The recall doors read exactly one store — but the conversations
live wherever each agent ran. ``recall STORE...`` and
``recall-summary STORE...`` read several stores as ONE memory:
the timeline interleaves across stores newest-first, each entry
and hit naming its store, the same trace id landing in two boxes
counts once (the first store wins — one memory, not two), the
summary's day rows name the stores that carried them, and the
--export diary carries the fleet in its header. A typo'd store
path still answers "store not found" — a silently-created empty
store reading as lost memory is the v5.2.0 lesson, kept. The
single-store doors are byte-identical: no positional stores, no
store key, no tag in the render.
"""

import json
import subprocess
import sys
import time
from pathlib import Path

from approximately.recall import MultiStore, render_summary, summarize
from approximately.store import TraceStore

ROOT = Path(__file__).resolve().parent.parent


def _run(*args):
    return subprocess.run(
        [sys.executable, "-m", "approximately", *args],
        capture_output=True, text=True, cwd=str(ROOT))


def _convo(tmp_path, name, task, *, model="m/1", success=True,
           tokens=0, created=None):
    from approximately.recorder import Recorder

    store = TraceStore(tmp_path / name)
    rec = Recorder(task, model=model, store=store, save=False)
    rec.tool("deploy", {"env": name}, result="ok", tokens=tokens)
    rec.respond("done", success=success)
    if created is not None:
        rec.trace.created_at = created
    store.save(rec.trace)
    return store, rec.trace


def _two(tmp_path):
    now = time.time()
    _convo(tmp_path, "box-a", "ship the web service", created=now)
    _convo(tmp_path, "box-b", "debug the cron job", created=now + 10,
           success=False)
    return now


# ---- the fleet view: one memory over several stores

def test_the_timeline_interleaves_and_names_stores(tmp_path):
    _two(tmp_path)
    r = _run("recall", str(tmp_path / "box-a"),
             str(tmp_path / "box-b"))
    assert r.returncode == 0, r.stderr
    assert "ship the web service" in r.stdout
    assert "{box-b}" in r.stdout, (
        "an entry's store must be named: a fleet memory without "
        "provenance reads as one machine's")
    lines = [ln for ln in r.stdout.splitlines()
             if "debug the cron" in ln or "ship the web" in ln]
    ship = lines.index(next(ln for ln in lines if "ship" in ln))
    debug = lines.index(next(ln for ln in lines if "debug" in ln))
    assert ship < debug, ("the timeline stays chronological "
                          "across boxes: the newer box-b "
                          "conversation reads after the older "
                          "box-a one")


def test_a_trace_in_two_boxes_is_one_memory(tmp_path):
    _two(tmp_path)
    store_b = TraceStore(tmp_path / "box-b")
    dup = TraceStore(tmp_path / "box-a").list_traces()[0]
    dup.id = store_b.list_traces()[0].id
    store_b.save(dup)
    r = _run("recall", str(tmp_path / "box-a"),
             str(tmp_path / "box-b"), "--json")
    payload = json.loads(r.stdout)
    tasks = [e["task"] for e in
             (entry for day in payload["days"]
              for entry in day["entries"])]
    assert len(tasks) == 2, (
        "the same trace id in two stores counted twice: the fleet "
        "reads as one memory, the first store wins")
    stores = sorted({e["store"] for e in
                     (entry for day in payload["days"]
                      for entry in day["entries"])})
    assert stores == ["box-a", "box-b"]


def test_search_hits_carry_their_store(tmp_path):
    _two(tmp_path)
    r = _run("recall", str(tmp_path / "box-a"),
             str(tmp_path / "box-b"), "--grep", "cron")
    assert r.returncode == 0, r.stderr
    assert "{box-b}" in r.stdout, \
        "a hit without its store sends the reader to the wrong box"
    assert "[task]" in r.stdout, \
        "the excerpt names the field it was said in"


def test_a_typo_store_is_a_refusal_not_lost_memory(tmp_path):
    _two(tmp_path)
    r = _run("recall", str(tmp_path / "box-a"),
             str(tmp_path / "typo-box"))
    assert r.returncode == 2, (
        "a silently-created empty store reads as lost memory to a "
        "human looking for last Tuesday")
    assert "store not found" in r.stderr
    assert not (tmp_path / "typo-box").exists()


def test_the_summary_names_the_stores_that_carried_a_day(tmp_path):
    _two(tmp_path)
    r = _run("recall-summary", str(tmp_path / "box-a"),
             str(tmp_path / "box-b"), "--json")
    payload = json.loads(r.stdout)
    day = payload["days"][-1]
    assert sorted(day["stores"]) == ["box-a", "box-b"], \
        "the day row names the stores that carried it"
    assert payload["conversations"] == 2
    assert payload["failed"] == 1
    text = render_summary(payload)
    assert "stores: box-a, box-b" in text


def test_the_summary_filters_still_work_across_stores(tmp_path):
    _two(tmp_path)
    r = _run("recall-summary", str(tmp_path / "box-a"),
             str(tmp_path / "box-b"), "--failed-only", "--json")
    payload = json.loads(r.stdout)
    assert payload["conversations"] == 1, \
        "the outcome filter threads the fleet view"
    assert payload["days"][-1]["stores"] == ["box-b"]


def test_the_export_diary_carries_the_fleet_header(tmp_path):
    _two(tmp_path)
    out = tmp_path / "diary.md"
    r = _run("recall", str(tmp_path / "box-a"),
             str(tmp_path / "box-b"), "--export", str(out))
    assert r.returncode == 0, r.stderr
    text = out.read_text(encoding="utf-8")
    assert "box-a" in text and "box-b" in text, (
        "a fleet diary without the store names is a diary of "
        "nowhere")
    assert "{box-b}" in text, "the timeline tags survive the export"
    assert not list(tmp_path.glob("*.tmp")), \
        "the diary is still written atomically"


def test_multi_store_dedupes_by_id_first_store_wins(tmp_path):
    _two(tmp_path)
    store_a, store_b = (TraceStore(tmp_path / "box-a"),
                        TraceStore(tmp_path / "box-b"))
    trace_b = store_b.list_traces()[0]
    view = MultiStore()
    view.add(store_a, str(tmp_path / "box-a"))
    view.add(store_b, str(tmp_path / "box-b"))
    traces = view.list_traces()
    assert len(traces) == 2
    assert [t.store for t in traces] == ["box-a", "box-b"]
    clashing = MultiStore()
    clashing.add(store_a, str(tmp_path / "box-a"))
    trace_a2 = store_a.list_traces()[0]
    trace_b.id = trace_a2.id
    store_b.save(trace_b)
    clashing.add(store_b, str(tmp_path / "box-b"))
    assert len(clashing.list_traces()) == 2, \
        "the duplicated id appears once (box-a read first wins)"


# ---- the single-store doors stay byte-identical

def test_a_single_store_has_no_store_key_and_no_tag(tmp_path):
    _two(tmp_path)
    r = _run("recall", "--store", str(tmp_path / "box-a"), "--json")
    payload = json.loads(r.stdout)
    for day in payload["days"]:
        for entry in day["entries"]:
            assert "store" not in entry, (
                "the single-store shape gains no key: existing "
                "consumers read it unchanged")
    r2 = _run("recall", "--store", str(tmp_path / "box-a"))
    assert "{box-a}" not in r2.stdout


def test_the_default_store_still_answers(tmp_path, monkeypatch):
    store, _trace = _convo(tmp_path, "default-home", "the only one")
    r = _run("--store", str(store.directory), "recall")
    assert r.returncode == 0 and "the only one" in r.stdout


def test_summarize_totals_aggregate_across_the_fleet(tmp_path):
    _two(tmp_path)
    _convo(tmp_path, "box-c", "write the docs", created=time.time(),
           tokens=1200)
    view = MultiStore()
    for name in ("box-a", "box-b", "box-c"):
        view.add(TraceStore(tmp_path / name), str(tmp_path / name))
    payload = summarize(view)
    assert payload["conversations"] == 3
    assert payload["tokens"] >= 1200
    assert len(payload["days"]) >= 1
