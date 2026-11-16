"""v581: the memory doors get a performance budget.

recall scans every conversation's every field on a grep; the
timeline sorts and groups the whole store; the summary
keyword-counts the tasks. Each must stay linear-ish in traces
and finish inside budget - the memory door a human leans on at
2am cannot be the one that hangs the store. The gate lives in
perf_gate (recall_gate, 2k traces, 5s budget) beside the other
doors; these pins keep the fleet view honest too: the
dedupe-by-id merge must not turn two stores into an O(n^2)
pairwise compare.
"""

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_the_gate_is_registered():
    src = (ROOT / "scripts" / "perf_gate.py").read_text(
        encoding="utf-8")
    assert "recall_gate()" in src, \
        "a gate no one calls is a decorative budget"
    assert "def recall_gate" in src


def test_the_gate_passes_in_the_full_run():
    r = subprocess.run(
        [sys.executable, "scripts/perf_gate.py"],
        capture_output=True, text=True, cwd=str(ROOT),
        timeout=600)
    assert r.returncode == 0, (
        f"perf gate failed:\n{r.stderr[-400:]}")
    assert "perf-gate[recall]" in r.stdout


def test_the_fleet_merge_stays_linear(tmp_path):
    from approximately.recall import MultiStore, search, timeline
    from approximately.recorder import Recorder
    from approximately.store import TraceStore

    for name in ("box-a", "box-b"):
        store = TraceStore(tmp_path / name)
        for i in range(300):
            rec = Recorder(f"run {i} - ship {i % 5}",
                           store=store, save=False)
            rec.tool("deploy", {"i": i}, result="x" * 150)
            rec.respond("done", success=True)
            store.save(rec.trace)
    view = MultiStore()
    view.add(TraceStore(tmp_path / "box-a"),
             str(tmp_path / "box-a"))
    view.add(TraceStore(tmp_path / "box-b"),
             str(tmp_path / "box-b"))
    start = time.perf_counter()
    traces = view.list_traces()
    merged = time.perf_counter() - start
    assert len(traces) == 600
    start = time.perf_counter()
    payload = timeline(view)
    timeline(view)
    assert payload["conversations"] == 600
    search(view, "ship 3", limit=20)
    fleet_elapsed = time.perf_counter() - start
    assert merged < 5.0 and fleet_elapsed < 5.0, (
        f"fleet merge {merged:.2f}s + doors {fleet_elapsed:.2f}s "
        "- the dedupe must not compare every record pairwise")
