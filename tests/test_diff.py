"""Structural trace diff: NW traceback, edit-script ops, CLI wiring."""

from __future__ import annotations

import pytest

from approximately.diff import Op, diff
from approximately.recorder import Recorder


def _run(search_from, seat, verify=True, result_extra=""):
    with Recorder("book flight", save=False) as rec:
        rec.tool("search", {"from": search_from},
                 result=f"JT-044 {search_from}{result_extra}")
        rec.tool("book", {"seat": seat}, result="BOOKED", mutating=True)
        if verify:
            rec.tool("get_booking", {"id": 1}, result="confirmed")
        rec.respond("done", success=True)
    return rec.trace


def test_identical_runs_all_equal():
    d = diff(_run("SFO", "12A"), _run("SFO", "12A"))
    assert d.similarity == pytest.approx(1.0)
    assert all(e.op == Op.EQUAL for e in d.entries)


def test_value_change_is_mutated_not_deleted():
    d = diff(_run("SFO", "12A"), _run("SFO", "24F"))
    mutated = [e for e in d.entries if e.op == Op.MUTATED]
    assert len(mutated) == 1
    assert mutated[0].a_tool == "book"
    assert d.entries[mutated[0].a_index].op  # a_index present


def test_missing_step_is_deleted():
    d = diff(_run("SFO", "12A"), _run("SFO", "12A", verify=False))
    deleted = [e for e in d.entries if e.op == Op.DELETED]
    assert len(deleted) == 1 and deleted[0].a_tool == "get_booking"


def test_extra_step_is_inserted():
    a = _run("SFO", "12A")
    from approximately.trace import TOOL_CALL, Step, Trace

    steps = [Step.from_dict(s.to_dict()) for s in a.steps]
    extra = Step(kind=TOOL_CALL, tool="cancel_booking", args={},
                 result="cancelled")
    steps.insert(2, extra)
    richer = Trace(task=a.task, model=a.model, success=a.success)
    for step in steps:
        richer.add(step)
    d = diff(a, richer)
    inserted = [e for e in d.entries if e.op == Op.INSERTED]
    assert len(inserted) == 1 and inserted[0].b_tool == "cancel_booking"


def test_diff_similarity_matches_aligner():
    from approximately.align import similarity as align_similarity

    a, b = _run("SFO", "12A"), _run("SFO", "24F")
    assert diff(a, b).similarity == pytest.approx(
        align_similarity(a, b), abs=0.01)


def test_summary_renders_symbols():
    d = diff(_run("SFO", "12A"), _run("SFO", "12A", verify=False))
    text = d.summary()
    assert "deleted" in text and "- " in text
    assert d.a_id in text and d.b_id in text


def test_diff_order_is_chronological():
    d = diff(_run("SFO", "12A"), _run("SFO", "12A", verify=False))
    a_indexes = [e.a_index for e in d.entries if e.a_index is not None]
    assert a_indexes == sorted(a_indexes)
