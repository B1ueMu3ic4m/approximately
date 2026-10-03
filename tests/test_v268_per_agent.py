"""Night VI, round 11: per-agent ceilings for multi-agent runs.

MAST's whole point is multi-agent failure — and a shared budget lets
one runaway agent hide inside the group total.  ``per_agent`` gives
each named agent its own token ceiling: it trips independently,
names the agent in the error, and lands in the stamp beside the
global meters.
"""

import pytest

from approximately.budget import Budget, BudgetExceededError
from approximately.recorder import Recorder


def test_one_runaway_agent_trips_alone():
    budget = Budget(per_agent={"researcher": 1_000,
                               "booker": 1_000_000})
    with Recorder("team task", model="m/1", save=False,
                  budget=budget) as rec:
        rec.tool("search", agent="researcher", tokens=1_500)
        rec.tool("book", agent="booker", tokens=100)
    reasons = budget.exceeded_reasons()
    assert reasons == ["agent:researcher"]
    assert rec.trace.meta is not None
    agents = budget.state["agents"]
    assert agents["researcher"]["exceeded"] is True
    assert agents["booker"]["exceeded"] is False
    assert agents["researcher"]["tokens"] == 1_500
    assert agents["researcher"]["limit"] == 1_000


def test_global_ceiling_trips_across_agents():
    budget = Budget(tokens=2_000, per_agent={"a": 1_000_000,
                                             "b": 1_000_000})
    with Recorder("team task", model="m/1", save=False,
                  budget=budget) as rec:
        rec.tool("x", agent="a", tokens=1_200)
        rec.tool("y", agent="b", tokens=1_200)
    assert budget.exceeded_reasons() == ["tokens"]
    assert budget.state["agents"]["a"]["exceeded"] is False
    assert budget.state["agents"]["b"]["exceeded"] is False


def test_raise_names_the_agent():
    budget = Budget(per_agent={"researcher": 1_000},
                    on_exceed="raise")
    with pytest.raises(BudgetExceededError) as ei, \
            Recorder("team task", model="m/1", save=False,
                     budget=budget) as rec:
        rec.tool("search", agent="researcher", tokens=1_500)
    assert ei.value.kind == "agent:researcher"
    assert "agent 'researcher'" in str(ei.value)
    # the offending step is on the record, attributed to the agent
    last = [s for s in rec.trace.steps if s.kind == "tool_call"][-1]
    assert last.agent == "researcher"


def test_unattributed_steps_only_move_the_global_meter():
    budget = Budget(tokens=5_000, per_agent={"a": 100})
    with Recorder("solo", model="m/1", save=False,
                  budget=budget) as rec:
        rec.tool("x", tokens=4_000)  # no agent named
    assert budget.exceeded_reasons() == []
    assert budget.state["agents"]["a"]["tokens"] == 0


def test_per_agent_validation():
    with pytest.raises(ValueError, match="positive ints"):
        Budget(per_agent={"a": 0})
    with pytest.raises(ValueError, match="positive ints"):
        Budget(per_agent={"a": -5})
    with pytest.raises(ValueError, match="positive ints"):
        Budget(per_agent={"a": True})
    with pytest.raises(ValueError, match="at least one ceiling"):
        Budget()


def test_warn_mode_names_the_agent(tmp_path, capsys):
    budget = Budget(per_agent={"researcher": 100}, on_exceed="warn")
    with Recorder("team task", model="m/1", save=False,
                  budget=budget) as rec:
        rec.tool("x", agent="researcher", tokens=150)
    err = capsys.readouterr().err
    assert "agent 'researcher' 150/100 tokens" in err


def test_stamp_shape_is_closed_under_no_per_agent():
    budget = Budget(tokens=100)
    with Recorder("solo", model="m/1", save=False,
                  budget=budget) as rec:
        rec.tool("x", tokens=10)
    assert "agents" not in rec.trace.meta["budget"]


def test_both_kinds_of_ceiling_can_trip_together():
    budget = Budget(tokens=2_000, per_agent={"a": 1_000})
    with Recorder("team task", model="m/1", save=False,
                  budget=budget) as rec:
        rec.tool("x", agent="a", tokens=2_500)
    assert budget.exceeded_reasons() == ["tokens", "agent:a"]
