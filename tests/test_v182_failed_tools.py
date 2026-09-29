"""v182: `failed_tools` joins the query DSL.

`tools contains search` matches any run that *used* search; night ops
want the runs where search *errored*. `failed_tools` is the derived
list of tool names whose tool-call step carries an error — so
`failed_tools contains 'search'` composes with everything:
`failed_tools contains 'search' and success == false`.
"""

from approximately.query import select
from approximately.recorder import Recorder


def _trace(task, error):
    rec = Recorder(task, save=False)
    rec.tool("search", {"q": 1}, result=None if error else "hit",
             error=error)
    rec.respond("done", success=error is None)
    return rec.trace


def test_failed_tools_selects_errored_runs():
    traces = [_trace("boom", "timeout"), _trace("fine", None)]
    hits = select(traces, "failed_tools contains 'search'")
    assert [t.task for t in hits] == ["boom"]


def test_composes_with_success_predicate():
    traces = [_trace("boom-but-passed", "timeout"),
              _trace("boom-and-failed", "timeout")]
    traces[0].success = True
    traces[1].success = False
    hits = select(traces, "failed_tools contains 'search' and "
                          "success == false")
    assert [t.task for t in hits] == ["boom-and-failed"]


def test_clean_runs_never_match():
    traces = [_trace("fine", None)]
    assert select(traces, "failed_tools contains 'search'") == []
