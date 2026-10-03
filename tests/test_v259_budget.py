"""Night VI, round 1: live budget rails on the recorder.

The ``ci`` gate settles accounts after the run; a Budget is the
circuit breaker DURING it.  These tests pin the three enforcement
modes, the pricing convention (4-dp spend, unpriced tokens counted
separately, never silently valued at zero), the exit stamp that the
signature covers, and the guarantee that the offending step is on the
record before the breaker trips.
"""

import pytest

from approximately.budget import Budget, BudgetExceededError
from approximately.integrity import sign, verify
from approximately.recorder import Recorder
from approximately.store import TraceStore


def test_token_ceiling_raise_stops_burn_with_step_on_record(tmp_path):
    store = TraceStore(tmp_path)
    budget = Budget(tokens=10_000, on_exceed="raise")
    with pytest.raises(BudgetExceededError) as ei, \
            Recorder("burn task", model="m/1", store=store,
                     budget=budget) as rec:
            rec.tool("cheap", tokens=4_000)
            rec.tool("pricey", tokens=12_000)
    assert ei.value.kind == "tokens"
    assert ei.value.limit == 10_000
    assert ei.value.spent == 16_000
    # __exit__ still ran: failure recorded, trace saved
    assert rec.trace.success is False
    assert rec.saved_path is not None
    saved = store.load(rec.trace.id)
    kinds = [s.kind for s in saved.steps]
    assert "error" in kinds  # the BudgetExceededError itself
    # the offending step made it onto the record BEFORE the trip
    assert saved.steps[-2].tokens == 12_000
    # exit stamp, signature-covered
    assert saved.meta["budget"]["exceeded"] is True
    assert saved.meta["budget"]["tokens"] == 16_000


def test_warn_mode_prints_once_per_ceiling(tmp_path, capsys):
    budget = Budget(tokens=100, on_exceed="warn")
    with Recorder("warn task", model="m/1", budget=budget) as rec:
        rec.tool("a", tokens=150)
        rec.tool("b", tokens=150)  # still over, NOT re-warned
    err = capsys.readouterr().err
    assert err.count("budget warning") == 1
    assert "150/100 tokens" in err
    assert rec.trace.success is not False  # warn never fails the run


def test_stamp_mode_is_silent_but_pinned_in_meta():
    budget = Budget(tokens=1_000)
    with Recorder("stamp task", model="m/1", save=False,
                  budget=budget) as rec:
        rec.tool("a", tokens=40)
        rec.tool("b", tokens=2_000)
    assert rec.trace.meta["budget"]["exceeded"] is True
    assert rec.trace.meta["budget"]["tokens"] == 2_040


def test_usd_ceiling_uses_house_pricing_convention():
    budget = Budget(usd=0.05, prices={"m/1": 0.01}, on_exceed="raise")
    with pytest.raises(BudgetExceededError) as ei, \
            Recorder("dollar task", model="m/1", save=False,
                     budget=budget) as rec:
        rec.tool("a", tokens=3_000)   # $0.03
        rec.tool("b", tokens=2_500)   # $0.025 -> $0.055 > $0.05
    assert ei.value.kind == "usd"
    assert ei.value.spent == pytest.approx(0.055)
    assert ei.value.limit == pytest.approx(0.05)


def test_unpriced_run_valued_never_at_zero_silently():
    # the charge key is the run's model; an unpriced model's tokens
    # land in unpriced_tokens instead of silently counting as $0 —
    # the usd ceiling must NOT be tripped by a valuation we invented
    budget = Budget(usd=1.0, prices={"m/priced": 0.5})
    with Recorder("mystery task", model="m/unknown", save=False,
                  budget=budget) as rec:
        rec.tool("a", tokens=4_000)
    st = rec.trace.meta["budget"]
    assert st["usd"] == 0.0
    assert st["unpriced_tokens"] == 4_000
    assert st["exceeded"] is False
    assert st["tokens"] == 4_000


def test_under_budget_state_is_clean():
    budget = Budget(tokens=10_000, usd=1.0, prices={"m/1": 0.01})
    with Recorder("calm task", model="m/1", save=False,
                  budget=budget) as rec:
        rec.tool("a", tokens=1_000)
    st = rec.trace.meta["budget"]
    assert st == {"tokens": 1_000, "usd": 0.01, "unpriced_tokens": 0,
                  "exceeded": False, "limit_tokens": 10_000,
                  "limit_usd": 1.0}


def test_no_budget_means_no_stamp():
    with Recorder("plain task", save=False) as rec:
        rec.tool("a", tokens=999)
    assert "budget" not in rec.trace.meta


def test_budget_validation():
    with pytest.raises(ValueError, match="at least one ceiling"):
        Budget()
    with pytest.raises(ValueError, match="price map"):
        Budget(usd=1.0)
    with pytest.raises(ValueError, match="on_exceed"):
        Budget(tokens=1, on_exceed="explode")


def test_stamped_budget_verifies_after_signing():
    key = b"night-vi-budget-key"
    budget = Budget(tokens=100)
    with Recorder("signed task", model="m/1", save=False,
                  budget=budget) as rec:
        rec.tool("a", tokens=500)
    sign(rec.trace, key=key)
    verdict = verify(rec.trace, key=key)
    assert verdict.signed and verdict.intact


def test_charge_is_public_and_stateful():
    b = Budget(tokens=100)
    st = b.charge(tokens=60, model="m/1")
    assert st["tokens"] == 60
    st = b.charge(tokens=60, model="m/1")
    assert st["tokens"] == 120
    assert st["exceeded"] is True
    assert b.exceeded_reasons() == ["tokens"]
