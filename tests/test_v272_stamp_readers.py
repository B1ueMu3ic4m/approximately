"""Night VI, round 15: the last two readers of the stamp.

The agent scorecard gains a ``breached_traces`` column (parallel to
``failed_traces`` — a trace the live rails stopped is a run-level
fact about every agent who touched it), and ``evidence --all``'s
archive index names which archived traces came home over budget.
"""

import json

from approximately.budget import Budget
from approximately.cluster import agent_scorecard
from approximately.evidence import build_store_packs
from approximately.fleet import webhook_payload
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _team(store_dir):
    store = TraceStore(store_dir)
    budget = Budget(per_agent={"researcher": 10})
    with Recorder("burn run", model="m/1", store=store,
                  budget=budget) as rec:
        rec.tool("search", agent="researcher", tokens=500)
        rec.tool("book", agent="booker", tokens=10)
        rec.respond("done", success=True)
    with Recorder("calm run", model="m/1", store=store) as rec:
        rec.tool("t", tokens=10)
        rec.respond("done", success=True)
    return store


def test_scorecard_counts_breached_traces(tmp_path):
    store = _team(tmp_path)
    rows = {r["agent"]: r for r in agent_scorecard(
        store.list_traces())}
    assert rows["researcher"]["breached_traces"] == 1
    # booker touched the breached run too — a run-level fact about
    # every participant, the unattributed respond step included
    assert rows["booker"]["breached_traces"] == 1
    assert rows["unattributed"]["breached_traces"] == 1
    # the calm run keeps its zero
    assert rows["unattributed"]["tokens"] >= 10


def test_scorecard_shape_unchanged_without_stamps(tmp_path):
    store = TraceStore(tmp_path)
    with Recorder("plain", model="m/1", store=store) as rec:
        rec.tool("t", tokens=5)
        rec.respond("done", success=True)
    rows = agent_scorecard(store.list_traces())
    assert all(r["breached_traces"] == 0 for r in rows)


def test_archive_index_names_breached_traces(tmp_path):
    store = _team(tmp_path / "s")
    out = tmp_path / "archive"
    result = build_store_packs(store, out)
    index = json.loads((out / "index.json").read_text(
        encoding="utf-8"))
    by_id = {t["trace_id"]: t for t in index["traces"]}
    burned = [t for t in by_id.values() if t["budget_breached"]]
    assert len(burned) == 1
    assert index["packs"] == 2
    assert result["packs"] == 2


def test_webhook_top_agents_carry_the_column(tmp_path):
    from approximately.fleet import survey
    store_dir = tmp_path / "s"
    _team(store_dir)
    payload = webhook_payload(survey([store_dir]))
    agents = payload["stores"][0]["top_agents"]
    by_name = {a["agent"]: a for a in agents}
    assert by_name["researcher"]["breached_traces"] == 1
    assert by_name["booker"]["breached_traces"] == 1


def test_scorecard_min_failed_filter_still_works(tmp_path):
    store = _team(tmp_path)
    rows = agent_scorecard(store.list_traces(), min_failed=1)
    assert rows == []  # nothing failed in this fixture
