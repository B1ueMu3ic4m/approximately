"""v510: the analysis engines meet junk on its feet.

The analysis-engines recon (query, cluster, drift, detectors,
anomaly, diff, merge, and their doors) found the same classes the
other rounds fixed everywhere else: a plain valid expression
(`tools contains (deploy, web)`) crashed the whole query door
with a TypeError; a foreign record with non-sequential step
indexes sent the repeat detector indexing past the end of the
list in every attribution consumer — and that record is
STORE-reachable (hand-edited JSON); drift's output flipped order
across processes because set iteration fed a stable sort's ties;
a NaN token counter compared False against every ceiling and
slipped silently; inf counters became bare Infinity in the
scorecard JSON and round(inf) OverflowError'd the door; API-built
junk (int agents, int tools, int results) TypeError'd or
AttributeError'd mid-door; a typo'd merge source was silently
created and merged 0 traces with exit 0.
"""

import json
import subprocess
import sys
from pathlib import Path

from approximately.cluster import agent_scorecard, tool_scorecard, trend
from approximately.drift import detect_drift
from approximately.query import select
from approximately.trace import Step, Trace

ROOT = Path(__file__).resolve().parent.parent


def _run(*args):
    return subprocess.run(
        [sys.executable, "-m", "approximately", *args],
        capture_output=True, text=True, cwd=str(ROOT))


def _trace(**kw):
    trace = Trace(**{"task": "t", "created_at": 1700000000.0, **kw})
    return trace


# ---- the query door: a valid expression is not a TypeError

def test_a_list_needle_against_a_set_field():
    both = _trace()
    both.add(Step(kind="tool_call", tool="deploy", result="ok"))
    both.add(Step(kind="tool_call", tool="web", result="ok"))
    one = _trace()
    one.add(Step(kind="tool_call", tool="web", result="ok"))
    hits = select([one, both], "tools contains (deploy, web)")
    assert len(hits) == 1 and hits[0] is both,  (
        "v1 crashed the whole door with 'cannot use list as set  "
        "element' on this plain expression")


def test_a_nan_counter_cannot_ride_a_ceiling():
    poisoned = _trace()
    poisoned.add(Step(kind="tool_call", tool="deploy",
                      tokens=float("nan"), error="boom"))
    honest = _trace()
    honest.add(Step(kind="tool_call", tool="deploy", tokens=500,
                    error="boom"))
    assert len(select([poisoned], "tokens > 100")) == 0,  (
        "nan > 100 is False: a poisoned trace used to slip every  "
        "ceiling silently")
    assert len(select([honest], "tokens > 100")) == 1


# ---- the store boundary: index is positional truth

def test_a_foreign_index_rip_cannot_reach_past_the_end():
    trace = Trace.from_dict({
        "id": "abcd1234ef01", "task": "gapped",
        "steps": [
            {"kind": "tool_call", "tool": "deploy", "result": "x",
             "index": 5},
            {"kind": "tool_call", "tool": "deploy", "result": "x",
             "index": 6},
        ]})
    assert [s.index for s in trace.steps] == [0, 1],  (
        "two identical calls with index 5,6 used to IndexError the  "
        "repeat detector in every attribution consumer")
    from approximately.cluster import cluster
    from approximately.counterfactual import counterfactual

    cluster([trace])
    counterfactual(trace)


# ---- drift: the same store, the same bytes, every process

def test_drift_output_is_byte_stable_across_runs():
    base = _trace()
    base.add(Step(kind="tool_call", tool="deploy", result="x"))
    cur = _trace()
    cur.add(Step(kind="tool_call", tool="build", result="x"))
    first = detect_drift([base], [cur]).top_shifted
    second = detect_drift([base], [cur]).top_shifted
    assert first == second,  (
        "set iteration fed the stable sort's ties: the same store  "
        "produced different orderings across processes")
    keys = [row[0] for row in first]
    assert keys == sorted(keys), \
        "ties break by name, deterministically"


# ---- the scorecards: inf is None, not invalid JSON

def test_inf_counters_read_none_not_infinity():
    hot = _trace()
    hot.add(Step(kind="tool_call", tool="x", tokens=float("inf"),
                 latency_ms=float("inf"), agent=7))
    warm = _trace()
    warm.add(Step(kind="tool_call", tool="x", tokens=5,
                  latency_ms=10, agent="alice", error="boom"))
    text = json.dumps(agent_scorecard([hot, warm])
                      + tool_scorecard([hot, warm]))
    assert "Infinity" not in text,  (
        "bare Infinity is invalid JSON, and round(inf) Overflow'd  "
        "the whole door")
    assert all(row["p95_tokens"] is None for row in
               agent_scorecard([hot])), "not measurable is None"


def test_mixed_type_names_sort_by_str():
    hot = _trace()
    hot.add(Step(kind="tool_call", tool="x", tokens=5, latency_ms=10,
                 agent=7, error="boom"))
    warm = _trace()
    warm.add(Step(kind="tool_call", tool="x", tokens=5, latency_ms=10,
                  agent="alice", error="boom"))
    rows = agent_scorecard([hot, warm])
    assert [str(r["agent"]) for r in rows] == (
        sorted(str(r["agent"]) for r in rows)), (
        "an int agent beside a str agent used to TypeError the "
        "sort on a steps tie")


# ---- trend: a non-finite epoch has no bucket

def test_trend_survives_an_inf_epoch():
    hot = _trace(created_at=float("inf"))
    hot.add(Step(kind="tool_call", tool="x", tokens=1, latency_ms=1))
    rows = trend([_trace(), _trace(created_at=200000.0), hot])
    assert len(rows) >= 1, \
        "inf - inf is NaN and int(NaN) was a ValueError mid-report"


# ---- the doors: junk answers by name

def test_a_typo_merge_source_is_a_refusal(tmp_path):
    store, _t = _stamp(tmp_path / "s")
    r = _run("--store", str(store.directory), "merge",
             str(tmp_path / "typo-store"), "--on-conflict", "skip")
    assert r.returncode == 2,  (
        "a typo'd source used to be silently created and merged 0  "
        "traces with exit 0")
    assert "not found" in r.stderr
    assert not (tmp_path / "typo-store").exists()


def _stamp(box):
    from approximately.recorder import Recorder
    from approximately.store import TraceStore

    store = TraceStore(box)
    rec = Recorder("analysis task", store=store)
    rec.tool("sh", {"cmd": "x"}, result="ok")
    rec.respond("done", success=True)
    store.save(rec.trace)
    return store, rec.trace


def test_a_hand_edited_annotation_row_is_skipped(tmp_path):
    store, _trace = _stamp(tmp_path / "target")
    source = tmp_path / "source"
    source.mkdir()
    (source / "annotations.jsonl").write_text(
        json.dumps({"note": "no trace_id here"}) + "\n", encoding="utf-8")
    r = _run("--store", str(store.directory), "merge", str(source))
    assert r.returncode == 0, (
        f"rc={r.returncode} err={r.stderr[-200:]}")
    assert "Traceback" not in r.stderr


def test_the_anomaly_doors_survive_int_tools():
    hot = _trace()
    hot.add(Step(kind="tool_call", tool=42, tokens=1, latency_ms=100))
    warm_traces = []
    for _ in range(6):
        warm = _trace()
        warm.add(Step(kind="tool_call", tool="sh", tokens=1,
                      latency_ms=10))
        warm_traces.append(warm)
    from approximately.anomaly import detect_fleet_anomalies

    detect_fleet_anomalies([hot, *warm_traces])


def test_diff_norms_non_string_results():
    from approximately.diff import diff

    a = _trace()
    a.add(Step(kind="tool_call", tool="deploy", args={"i": 1},
               result="ok"))
    b = _trace()
    b.add(Step(kind="tool_call", tool="deploy", args={"i": 2},
               result=42))
    report = diff(a, b)
    assert report is not None, (
        "a mutated pair with result=42 used to AttributeError "
        "mid-bisect")


def test_last_zero_is_a_refusal_not_the_whole_store(tmp_path):
    store, _trace = _stamp(tmp_path / "s")
    r = _run("--store", str(store.directory), "cluster", "--last", "0")
    assert r.returncode == 2,  (
        "--last 0 is truthy-zero: it used to slice to the whole  "
        "store (traces[-0:])")
    assert "--last" in r.stderr
