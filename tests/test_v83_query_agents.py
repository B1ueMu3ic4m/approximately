"""v83: query DSL `agents` field — multi-agent selections over identity.

``agents contains 'researcher'`` selects traces where a named agent
performed a step. Steps without identity contribute nothing; the
unattributed bucket stays a stats --by-agent concern, not a query
semantics.
"""

from approximately.cli import build_parser
from approximately.query import select
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _crew_store(tmp_path):
    store = TraceStore(str(tmp_path / "s"))
    crew = Recorder("crew run", save=False)
    crew.tool("search", {"q": "x"}, result="y", agent="researcher")
    crew.respond("done", success=False, agent="lead")
    store.save(crew.trace)

    solo = Recorder("solo run", save=False)
    solo.respond("done", success=False)
    store.save(solo.trace)
    return store


def test_agents_contains_selects_by_identity(tmp_path):
    store = _crew_store(tmp_path)
    traces = store.list_traces()
    hits = select(traces, "agents contains 'researcher'")
    assert [t.id for t in traces if t.id != solo_id(traces)] == [
        t.id for t in hits]


def solo_id(traces):
    return next(t.id for t in traces if not any(
        s.agent for s in t.steps))


def test_agents_combined_with_other_predicates(tmp_path):
    store = _crew_store(tmp_path)
    traces = store.list_traces()
    hits = select(traces,
                  "agents contains 'lead' and success == false")
    assert len(hits) == 1
    hits = select(traces, "agents contains 'lead' and success == true")
    assert hits == []


def test_unattributed_steps_do_not_match(tmp_path):
    store = _crew_store(tmp_path)
    traces = store.list_traces()
    solo = next(t for t in traces if t.task == "solo run")
    hits = select([solo], "agents contains 'lead'")
    assert hits == []


def test_unknown_field_error_still_names_fields():
    try:
        select([], "agentz contains 'x'")
        raised = False
    except Exception as exc:
        raised = "agents" in str(exc)  # error lists the new field
    assert raised


def test_cli_query_agents(tmp_path, capsys):
    store = _crew_store(tmp_path)
    parser = build_parser()
    args = parser.parse_args(["query", "agents contains 'researcher'",
                              "--store", str(store.directory)])
    assert args.func(args) == 0
    out = capsys.readouterr().out
    assert "1 matching trace(s)" in out
