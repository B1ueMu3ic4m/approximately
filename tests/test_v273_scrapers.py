"""Night VI, round 17: the stamp reaches the scrapers and the
spreadsheets.

Prometheus entity renderings gain an
``approximately_{tool,agent}_breached_traces`` counter next to
``failed_traces``; CSV export gains a ``budget_breached`` column so a
spreadsheet can filter the burn without unpacking JSON.
"""

import csv

from approximately.budget import Budget
from approximately.cluster import agent_scorecard, tool_scorecard
from approximately.exporter import export_store
from approximately.metrics import render_agent_prometheus, render_tool_prometheus
from approximately.recorder import Recorder
from approximately.store import TraceStore


def tool_scorecard_rows(store):
    return tool_scorecard(store.list_traces())


def agent_scorecard_rows(store):
    return agent_scorecard(store.list_traces())


def _team(store_dir):
    store = TraceStore(store_dir)
    budget = Budget(per_agent={"researcher": 10})
    with Recorder("burn run", model="m/1", store=store,
                  budget=budget) as rec:
        rec.tool("search", agent="researcher", tokens=500)
        rec.respond("done", success=True)
    with Recorder("calm run", model="m/1", store=store) as rec:
        rec.tool("t", agent="booker", tokens=10)
        rec.respond("done", success=True)
    return store


def test_tool_prometheus_has_breach_counter(tmp_path):
    store = _team(tmp_path)
    text = render_tool_prometheus(tool_scorecard_rows(store))
    assert "approximately_tool_breached_traces_total" in text
    search_line = [line for line in text.splitlines()
                   if 'tool="search"' in line
                   and "breached_traces" in line and "}" in line]
    assert search_line and search_line[0].endswith(" 1")


def test_agent_prometheus_has_breach_counter(tmp_path):
    store = _team(tmp_path)
    text = render_agent_prometheus(agent_scorecard_rows(store))
    researcher = [line for line in text.splitlines()
                 if 'agent="researcher"' in line
                 and "breached_traces" in line and "}" in line]
    booker = [line for line in text.splitlines()
              if 'agent="booker"' in line
              and "breached_traces" in line and "}" in line]
    assert researcher and researcher[0].endswith(" 1")
    assert booker and booker[0].endswith(" 0")


def test_csv_column_filters_the_burn(tmp_path):
    store = _team(tmp_path)
    out = tmp_path / "steps.csv"
    export_store(store, out, fmt="csv")
    rows = list(csv.reader(out.read_text(
        encoding="utf-8").splitlines()))
    header = rows[0]
    assert header[12] == "budget_breached"
    col = header.index("budget_breached")
    agent_col = header.index("agent")
    by_agent = {row[agent_col]: row[col] for row in rows[1:]}
    assert by_agent["researcher"] == "True"
    assert by_agent["booker"] == "False"


def test_csv_injection_defense_untouched(tmp_path):
    store = TraceStore(tmp_path)
    with Recorder("formula", model="m/1", store=store) as rec:
        rec.tool("note", {}, result="=cmd|' /C calc'!A0")
        rec.respond("done", success=True)
    out = tmp_path / "steps.csv"
    export_store(store, out, fmt="csv")
    rows = list(csv.reader(out.read_text(
        encoding="utf-8").splitlines()))
    assert rows[1][rows[0].index("result")].startswith("'=")
