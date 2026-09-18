"""v0.38 — cycle-grade repetition (FM-1.3 step 2) + repeat prefilter."""

import time
import uuid
from pathlib import Path

from approximately.detectors import (
    ALL_DETECTORS,
    CycleRepeatDetector,
    run_rules,
)
from approximately.prose import _JACCARD_FLOOR, ProseRepeatDetector
from approximately.trace import TOOL_CALL, Step, Trace

CORPUS = Path(__file__).resolve().parent.parent / "docs" / "mast-bench-multi.jsonl"


def _call_steps(tools, results=None):
    steps = []
    for i, tool in enumerate(tools):
        steps.append(Step(index=i, kind=TOOL_CALL, tool=tool,
                          args={"n": i},
                          result=(results[i] if results else "ok")))
    return steps


def _trace(steps, prose=True):
    t = Trace(id="t38", task="ship the release", steps=steps)
    t.meta["prose"] = prose
    return t


def _loop(tool_names, repeats, period=None):
    period = period or len(tool_names)
    tools = []
    for _ in range(repeats):
        tools.extend(tool_names)
    return _call_steps(tools)


def test_cycle_fires_on_inner_agent_loop():
    # planner -> navigator -> editor x 7 = 21 calls in one cycle
    det = CycleRepeatDetector().detect(
        _trace(_loop(["planner", "navigator", "editor"], 7)))
    assert det is not None and det.mode_id == "FM-1.3"
    text = " ".join(str(e) for e in det.evidence)
    assert "21 calls" in text and "planner -> navigator -> editor" in text


def test_cycle_quiet_below_threshold():
    # 15 calls in the same cycle: one short of the floor — ordinary
    # iteration, not repetition-grade stagnation
    assert CycleRepeatDetector().detect(
        _trace(_loop(["planner", "navigator", "editor"], 5))) is None


def test_cycle_ignores_errored_calls():
    tools = ["planner", "navigator", "editor"] * 9
    steps = [Step(index=i, kind=TOOL_CALL, tool=tool,
                  args={"n": i}, result="ok",
                  error="boom" if i % 2 else None)
             for i, tool in enumerate(tools)]
    assert CycleRepeatDetector().detect(_trace(steps)) is None


def test_cycle_quiet_on_varied_single_agent_calls():
    tools = [f"tool_{uuid.uuid4().hex[:6]}" for _ in range(30)]
    assert CycleRepeatDetector().detect(_trace(_call_steps(tools))) is None


def test_prose_family_runs_cycle_detector():
    trace = _trace(_loop(["planner", "navigator", "editor"], 7))
    modes = {d.mode_id for d in run_rules(trace)}
    assert "FM-1.3" in modes


def test_tool_family_runs_cycle_detector():
    assert any(isinstance(d, CycleRepeatDetector) for d in ALL_DETECTORS)
    trace = _trace(_loop(["fetch", "parse", "store", "report"], 4),
                   prose=False)
    modes = {d.mode_id for d in run_rules(trace)}
    assert "FM-1.3" in modes


def test_repeat_prefilter_keeps_true_positive():
    base = "Investigate the failing deploy pipeline and roll back the bad build. "
    # repetition anchored at the opening turn belongs to the restart
    # detector, so anchor at turn 1 to exercise this detector's path
    turns = ["Kick off the incident review.", base + "Detail one.",
             base + "Detail one.", base + "Detail two."]
    steps = [Step(index=i, kind=TOOL_CALL, tool="say", args={}, result=t)
             for i, t in enumerate(turns)]
    det = ProseRepeatDetector().detect(_trace(steps))
    assert det is not None


def test_repeat_prefilter_prunes_distinct_turns():
    steps = [Step(index=i, kind=TOOL_CALL, tool="say", args={},
                  result=f"run {uuid.uuid4().hex * 40}")
             for i in range(120)]
    t0 = time.perf_counter()
    det = ProseRepeatDetector().detect(_trace(steps))
    elapsed = time.perf_counter() - t0
    assert det is None
    assert elapsed < 2.0, f"prefilter failed to prune: {elapsed:.2f}s"


def test_prefilter_floor_is_conservative():
    # anything the floor prunes must be far from near-verbatim
    from approximately.prose import _jaccard, _shingles
    a = _shingles("deploy the API service to production now")
    b = _shingles("deploy the API service to production now!")
    assert _jaccard(a, b) >= _JACCARD_FLOOR


def test_corpus_fm13_regression():
    """Pin the v0.38 gain: cycle detection lifts FM-1.3 recall on the
    multi-agent gold corpus while precision stays high."""
    import json

    from approximately.distill import evaluate_multi

    if not CORPUS.exists():
        return  # corpus is docs material, not a package dependency
    pairs = []
    for line in CORPUS.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        raw = json.loads(line)
        rec = dict(raw)
        labels = rec.pop("labels")
        trace = Trace.from_dict(rec)
        pairs.append((trace, labels))
    multi = evaluate_multi(pairs)
    fm13 = multi.per_mode.get("FM-1.3")
    assert fm13, "FM-1.3 missing from corpus evaluation"
    assert fm13["recall"] >= 0.5, fm13
    assert fm13["precision"] >= 0.8, fm13
