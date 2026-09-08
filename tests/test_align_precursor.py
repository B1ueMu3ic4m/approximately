"""v0.4 algorithms: Needleman-Wunsch trajectory alignment and the
failure-precursor n-gram predictor."""

from __future__ import annotations

import pytest

from approximately.align import align_score, normalize_step, similarity
from approximately.cluster import cluster
from approximately.precursor import mine
from approximately.recorder import Recorder

# ---- alignment ---------------------------------------------------------------

def _trace(actions):
    with Recorder("alignment probe", save=False) as rec:
        for tool, args in actions:
            rec.tool(tool, args, result="ok")
        rec.respond("done", success=True)
    return rec.trace


def test_normalize_step_identity_and_structure():
    step = _trace([("search", {"from": "SFO"})]).steps[0]
    identity, structure = normalize_step(step)
    assert identity == 'tool_call:search:from="SFO"'
    assert structure == "tool_call:search {from}"


def test_similarity_properties():
    a = _trace([("search", {"q": "A"}), ("book", {"id": 1}),
                ("verify", {"id": 1})])
    assert similarity(a, a) == pytest.approx(1.0)          # self-similarity
    same_shape = _trace([("search", {"q": "B"}), ("book", {"id": 2}),
                         ("verify", {"id": 2})])
    different = _trace([("email", {"to": "x"}), ("pay", {"amt": 5}),
                        ("notify", {})])
    # same shape, different values: half credit per aligned step
    assert 0.45 < similarity(a, same_shape) < 0.95
    assert similarity(a, a) > similarity(a, same_shape) >= similarity(a, different)
    assert similarity(a, different) == pytest.approx(0.0)  # nothing in common
    # symmetry
    assert similarity(a, different) == similarity(different, a)


def test_align_score_empty_sequences():
    assert align_score([], []) == 0.0
    tokens = [("tool_call:t:x", "tool_call:t {}")]
    assert align_score(tokens, []) == -1.0  # pure gap
    assert align_score([], tokens) == -1.0


def test_cluster_uses_alignment_for_similar_groups():
    """A trace whose actions mirror a failed cluster joins it under
    alignment similarity even when values differ."""
    traces = []
    for i, (origin, seat) in enumerate(
            [("SFO", "12A"), ("NRT", "3C"), ("LAX", "5B")]):
        with Recorder(f"booking run {i}", save=False) as rec:
            rec.tool("search", {"origin": origin}, result="JT-044")
            rec.tool("book", {"seat": seat}, result="BOOKED")
            rec.respond("Booked.", success=False)   # unverified booking
        traces.append(rec.trace)
    report = cluster(traces)
    assert report.failures_found == 3
    top = report.clusters[0]
    assert top.size == 3 and top.mode_id == "FM-3.1"


# ---- precursor prediction ------------------------------------------------------

def _observation_store():
    """Mine a store with a strong statistical pattern:
    detonate-after-arm -> always fails; safe_path -> always succeeds."""
    traces = []
    for i in range(10):
        with Recorder(f"armed run {i}", save=False) as rec:
            rec.tool("arm", {"i": i}, result="armed")
            rec.tool("detonate", {}, error="boom")
            rec.fail("boom")
        traces.append(rec.trace)
    for i in range(10):
        with Recorder(f"safe run {i}", save=False) as rec:
            rec.tool("walk", {"i": i}, result="ok")
            rec.respond("fine", success=True)
        traces.append(rec.trace)
    return traces


def test_precursor_flags_known_bad_prefix():
    traces = _observation_store()
    model = mine(traces)
    # a live run that armed and is about to detonate
    with Recorder("live run", save=False) as rec:
        rec.tool("arm", {"i": "live"}, result="armed")
        rec.tool("detonate", {}, error="boom")
    score = model.probability(rec.trace)
    assert score.probability > 0.7
    assert score.verdict == "HIGH RISK"


def test_precursor_clears_safe_prefix():
    traces = _observation_store()
    model = mine(traces)
    with Recorder("live safe", save=False) as rec:
        rec.tool("walk", {"i": "live"}, result="ok")
    score = model.probability(rec.trace)
    assert score.probability < 0.3
    assert score.verdict == "normal"


def test_precursor_unseen_prefix_is_honest_prior():
    traces = _observation_store()
    model = mine(traces)
    with Recorder("brand new shape", save=False) as rec:
        rec.tool("quantum_flip", {}, result="?")
    score = model.probability(rec.trace)
    assert score.probability == pytest.approx(0.5)
    assert "prior 0.5" in score.summary()


def test_precursor_support_is_capped():
    """One pattern seen 100 times must not gain unbounded weight."""
    traces = []
    for i in range(100):
        with Recorder(f"hot run {i}", save=False) as rec:
            rec.tool("hot_step", {}, error="x")
            rec.fail("x")
        traces.append(rec.trace)
    model = mine(traces)
    with Recorder("hot live", save=False) as rec:
        rec.tool("hot_step", {}, error="x")
    score = model.probability(rec.trace)
    assert 0.9 < score.probability < 1.0  # high, but finite
