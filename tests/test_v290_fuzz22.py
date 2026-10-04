"""Night VII, round 10: fuzz 22 — the new meters under hostile input.

Probes found two real holes, now fixed and pinned: a poisoned trace
whose step.result is a NUMBER crashed both the result meter and the
composition walk (len() on an int), and a digest row with negative
failures made the reliability budget GROW as the fleet burned.
Digest rows are untrusted input; the meters skip data lies.
"""


from approximately.anomaly import (
    detect_fleet_result_anomalies,
    detect_result_anomalies,
)
from approximately.context import composition
from approximately.forecast import failure_budget
from approximately.recorder import Recorder


def _poison_trace():
    with Recorder("poison", model="m/1", save=False) as rec:
        for _ in range(6):
            step = rec.tool("t", {}, result="x" * 100)
            step.result = 12345  # the json lied about the type
        rec.respond("done", success=True)
    return rec.trace


def test_poison_result_never_crashes_the_meter():
    assert detect_result_anomalies(_poison_trace()) == []


def test_poison_result_never_crashes_the_fleet_meter():
    assert detect_fleet_result_anomalies([_poison_trace()]) == []


def test_poison_result_never_crashes_composition():
    payload = composition(_poison_trace())
    assert payload["total_tokens"] >= 0
    # non-string results contribute nothing (data lies are free)
    assert all(p["kind"] != "tool_call" or p["tokens"] >= 0
               for p in payload["parts"])


def test_composition_survives_unserializable_args():
    with Recorder("weird args", model="m/1", save=False) as rec:
        rec.tool("t", {"k": object()}, result="x" * 500)
        rec.respond("done", success=True)
    payload = composition(rec.trace)
    assert payload["total_tokens"] > 0


def test_negative_failures_cannot_grow_the_budget():
    days = [{"day": "2026-10-01", "failures": -5},
            {"day": "2026-10-02", "failures": 3}]
    fb = failure_budget(days, allowance=10)
    assert fb["burned"] == 3  # the -5 lie is clamped to zero


def test_zero_allowance_is_exhausted_by_anything():
    days = [{"day": "2026-10-01", "failures": 1},
            {"day": "2026-10-02", "failures": 0}]
    fb = failure_budget(days, allowance=0)
    assert fb["burn_fraction"] is None  # division refused
    assert fb["exhausted"] is True


def test_huge_counts_do_not_overflow():
    days = [{"day": "2026-10-01", "failures": 10 ** 12},
            {"day": "2026-10-02", "failures": 10 ** 12}]
    fb = failure_budget(days, allowance=1)
    assert fb["exhausted"] is True
    assert fb["days_to_exhaustion"] == 0
    assert all(p["remaining"] == 0 for p in fb["projection"])


def test_digest_rows_with_missing_failures_key():
    days = [{"day": "2026-10-01"}, {"day": "2026-10-02",
                                    "failures": 2}]
    fb = failure_budget(days, allowance=5)
    assert fb["burned"] == 2  # missing key reads as zero
