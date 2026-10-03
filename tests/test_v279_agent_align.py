"""Night VI, round 23: one participant's trajectory.

``similar --agent NAME`` aligns a single agent's action stream
instead of the interleaved multi-agent run — two research agents
taking different paths inside otherwise identical runs are now
distinguishable, and the interleaved noise (messages, responses,
other agents' steps) stops diluting the alignment.
"""

import json

from approximately.align import similar_payload, tokens
from approximately.cli import main
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _team(store, task, researcher_tools, booker_tools):
    with Recorder(task, model="m/1", store=store) as rec:
        for t in researcher_tools:
            rec.tool(t, {}, agent="researcher")
        for t in booker_tools:
            rec.tool(t, {}, agent="booker")
        rec.respond("done", success=True)
    return rec.trace


def _store(tmp_path):
    store = TraceStore(tmp_path / "s")
    _team(store, "route A", ["search", "compare", "search"],
          ["book"])
    _team(store, "route A again", ["search", "compare", "search"],
          ["book"])
    _team(store, "route B", ["search", "guess", "book"],
          ["book"])
    return store


def test_tokens_filter_by_agent(tmp_path):
    store = _store(tmp_path)
    trace = store.list_traces()[0]
    assert len(tokens(trace)) == 4  # interleaved stream
    assert len(tokens(trace, agent="researcher")) == 3
    assert len(tokens(trace, agent="booker")) == 1
    assert tokens(trace, agent="nobody") == []


def test_agent_scoped_ranking_distinguishes_routes(tmp_path):
    store = _store(tmp_path)
    target = store.list_traces()[0]
    payload = similar_payload(target, store.list_traces(),
                              agent="researcher")
    assert payload["agent"] == "researcher"
    matches = {m["id"]: m["similarity"] for m in payload["matches"]}
    # route A again aligns perfectly on the researcher stream
    assert matches[store.list_traces()[1].id] == 1.0
    assert matches[store.list_traces()[2].id] < 1.0


def test_interleaved_stream_masks_the_difference(tmp_path):
    store = _store(tmp_path)
    traces = store.list_traces()
    target = traces[0]
    route_b = traces[2].id
    interleaved = {m["id"]: m["similarity"]
                   for m in similar_payload(target,
                                            store.list_traces())
                   ["matches"]}
    scoped = {m["id"]: m["similarity"]
              for m in similar_payload(target, store.list_traces(),
                                       agent="researcher")["matches"]}
    # without the agent filter the booker's identical step props up
    # route B's score relative to the scoped ranking
    assert interleaved[route_b] > scoped[route_b]


def test_cli_door_passes_the_filter(tmp_path, capsys):
    store = _store(tmp_path)
    trace = store.list_traces()[0]
    rc = main(["similar", trace.id, "--store", str(store.directory),
               "--agent", "researcher", "--json"])
    out = capsys.readouterr().out
    assert rc == 0
    payload = json.loads(out)
    assert payload["agent"] == "researcher"
    assert payload["matches"][0]["similarity"] == 1.0
