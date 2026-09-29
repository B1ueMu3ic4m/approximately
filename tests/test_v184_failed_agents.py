"""v184: `failed_agents` — the multi-agent half of the pair.

`agents contains researcher` matches any run researcher touched;
`failed_agents contains researcher` matches the runs where a tool
call *carrying researcher's name* errored. Sorted and deduplicated
(a repeat-offender agent erroring three times lists once), so
contains-semantics stay clean.
"""

from approximately.query import select
from approximately.recorder import Recorder


def _seed():
    traces = []
    rec = Recorder("researcher error", save=False)
    rec.tool("search", {"q": "x"}, result=None, error="timeout",
             agent="researcher")
    rec.respond("gave up", success=False, agent="researcher")
    traces.append(rec.trace)
    rec2 = Recorder("clean", save=False)
    rec2.tool("search", {"q": "y"}, result="hit")
    rec2.respond("done", success=True)
    traces.append(rec2.trace)
    rec3 = Recorder("other agent error", save=False)
    rec3.tool("deploy", {}, result=None, error="boom",
              agent="deployer")
    rec3.respond("nope", success=False, agent="deployer")
    traces.append(rec3.trace)
    return traces


def test_failed_agents_selects_the_named_agent():
    hits = select(_seed(), "failed_agents contains 'researcher'")
    assert [t.task for t in hits] == ["researcher error"]


def test_sorted_and_deduplicated():
    rec = Recorder("repeat offender", save=False)
    for _ in range(3):
        rec.tool("search", {}, result=None, error="timeout",
                 agent="researcher")
    rec.respond("gave up", success=False, agent="researcher")
    hits = select([rec.trace],
                  "failed_agents contains 'researcher'")
    assert len(hits) == 1
    # the underlying list is sorted+unique
    from approximately.query import _field_getter

    getter = _field_getter("failed_agents")
    assert getter(rec.trace) == ["researcher"]


def test_unnamed_errors_stay_out():
    rec = Recorder("no agent name", save=False)
    rec.tool("search", {}, result=None, error="timeout")
    rec.respond("gave up", success=False)
    assert select([rec.trace],
                  "failed_agents contains 'researcher'") == []
