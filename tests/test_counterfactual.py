"""Counterfactual root-cause analysis: do(step = ∅) experiments."""

from __future__ import annotations

from approximately.counterfactual import counterfactual, counterfactual as _cf
from approximately.recorder import Recorder


def _booking_trace():
    with Recorder("booking failure", save=False) as rec:
        rec.plan("search and book")
        rec.tool("search", {"q": "SFO"}, result="JT-044")
        rec.tool("search", {"q": "SFO"}, result="JT-044")   # FM-1.3
        rec.tool("book", {"seat": "12A"}, result="BOOKED", mutating=True)
        rec.respond("done", success=False)                   # FM-3.1
    return rec.trace


def test_root_cause_identified_for_local_failure():
    trace = _booking_trace()
    report = counterfactual(trace)
    by_pair = {(i.removed_step, i.mode_id): i.eliminated
               for i in report.interventions}
    # removing a duplicate search kills FM-1.3
    assert by_pair[(2, "FM-1.3")] is True
    # removing the unverified booking kills FM-3.2
    assert by_pair[(3, "FM-3.2")] is True
    # removing the premature response kills FM-3.1
    assert by_pair[(4, "FM-3.1")] is True


def test_symptoms_are_labeled_as_symptoms():
    """A derailment detection survives removing its flagged step when the
    OTHER irrelevant calls remain — a genuine symptom, not a root."""
    with Recorder("cook pasta carbonara", save=False) as rec:
        rec.tool("stock_trade", {"ticker": "AAPL"}, result="bought")   # 0
        rec.tool("upload_photo", {"album": "cats"}, result="ok")       # 1
        rec.tool("boil_water", {"liters": 2}, result="boiling")        # 2
        rec.tool("format_disk", {}, result="done")                     # 3
        rec.respond("cooked?", success=False)                          # 4
    report = counterfactual(rec.trace)
    symptoms = [(i.removed_step, i.mode_id) for i in report.interventions
                if not i.eliminated]
    assert symptoms, "derailment must persist while siblings remain"
    assert {mode for _, mode in symptoms} == {"FM-2.3"}


def test_each_loop_occurrence_is_a_root_and_derailment_is_distributed():
    """A wide 3-search loop: each single removal breaks the 3-recurrence
    signature (root), while derailment persists across its irrelevant
    calls (distributed cause)."""
    with Recorder("wide loop", save=False) as rec:
        rec.plan("loop")
        rec.tool("search", {"q": 1}, result="r")           # step 1
        for filler in range(2, 8):                          # 2..7
            rec.tool(f"filler_{filler}", {}, result="x")
        rec.tool("search", {"q": 1}, result="r")           # step 8
        for filler in range(9, 15):                         # 9..14
            rec.tool(f"filler_{filler}", {}, result="x")
        rec.tool("search", {"q": 1}, result="r")           # step 15
        rec.fail("failed after the loop")
    report = counterfactual(rec.trace)
    loop_ints = [i for i in report.interventions if i.mode_id == "FM-1.5"]
    assert len(loop_ints) == 1 and loop_ints[0].eliminated
    assert loop_ints[0].removed_step == 15  # the last loop occurrence
    assert "FM-2.3" in report.distributed_causes  # derailment survives removals


def test_causal_ranking_orders_by_eliminated_modes():
    trace = _booking_trace()
    report = counterfactual(trace)
    assert report.causal_ranking, "ranking present"
    counts = [len([i for i in report.interventions
                   if i.removed_step == step and i.eliminated])
              for step in report.causal_ranking]
    assert counts == sorted(counts, reverse=True)


def test_summary_mentions_root_causes():
    text = counterfactual(_booking_trace()).summary()
    assert "root-cause steps" in text
    assert "baseline:" in text


def test_exported_alias_is_the_same_function():
    assert _cf is counterfactual
