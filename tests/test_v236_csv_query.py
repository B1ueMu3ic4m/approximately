"""v236: the spreadsheet door, and three new query operators.

CSV export is one row per STEP — the shape a spreadsheet can pivot
without unpicking JSON (tokens/latency/errors per tool per run).
The query DSL gains `endswith`, `matches` (a bounded, parse-time-
compiled regex — the pattern arrives on a command line, so it is
attacker-adjacent) and `in` with a list literal, so "did this run
touch any of these five tools" stops being five `or` clauses.
"""

import csv
import json

import pytest

from approximately.cli import main
from approximately.exporter import export_store
from approximately.query import QueryError, parse, select
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _seed(path):
    store = TraceStore(path)
    rec = Recorder("book a flight", model="gpt-x", store=store,
                   save=False)
    rec.tool("search", {"q": "SFO,NRT"}, tokens=100, latency_ms=200)
    rec.tool("book_flight", {"id": "JT-044"}, tokens=40, latency_ms=900,
             result="BOOKED confirmation #B-2231, seat 12A")
    rec.respond("done", success=True)
    store.save(rec.trace)
    rec = Recorder("deploy on friday", model="gpt-x", store=store,
                   save=False)
    rec.tool("deploy", {"env": "prod"}, tokens=10, latency_ms=4000,
             error="timeout after 30s")
    rec.respond("rolled back", success=False)
    store.save(rec.trace)
    return store


# --- csv export -------------------------------------------------------

def test_csv_one_row_per_step(tmp_path):
    store = _seed(tmp_path / "s")
    out = tmp_path / "steps.csv"
    payload = export_store(store, out, fmt="csv")
    assert payload["written"] == 5 and payload["format"] == "csv"
    rows = list(csv.reader(out.read_text(encoding="utf-8").splitlines()))
    assert rows[0][:8] == ["trace_id", "task", "model", "success",
                           "created_at", "step", "kind", "tool"]
    assert len(rows) == 6                          # header + 5 steps
    search = next(r for r in rows if r[7] == "search")
    assert search[9] == "100" and search[10] == "200"


def _rows(path):
    # newline="": a quoted cell may span physical lines, so the csv
    # module — not splitlines — owns line splitting
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.reader(fh))


def test_csv_quotes_and_embedded_newlines_survive(tmp_path):
    store = TraceStore(tmp_path / "s")
    rec = Recorder("tricky, task", store=store, save=False)
    rec.tool("note", {}, result="line one\nline two, with comma")
    rec.respond("done", success=True)
    store.save(rec.trace)
    out = tmp_path / "s.csv"
    export_store(store, out, fmt="csv")
    rows = _rows(out)
    assert rows[1][12] == "line one\nline two, with comma"


def test_csv_caps_free_text(tmp_path):
    store = TraceStore(tmp_path / "s")
    rec = Recorder("big", store=store, save=False)
    rec.tool("note", {}, result="x" * 5000)
    rec.respond("done", success=True)
    store.save(rec.trace)
    out = tmp_path / "s.csv"
    export_store(store, out, fmt="csv")
    rows = list(csv.reader(out.read_text(encoding="utf-8").splitlines()))
    assert len(rows[1][12]) == 240
    assert rows[1][12].endswith("…")


def test_csv_via_cli_door(tmp_path, capsys):
    _seed(tmp_path / "s")
    out = tmp_path / "s.csv"
    code = main(["export", "--store", str(tmp_path / "s"),
                 "--format", "csv", str(out), "--json"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["format"] == "csv" and payload["written"] == 5
    assert out.exists()


# --- query operators --------------------------------------------------

def _traces(tmp_path):
    return _seed(tmp_path / "q").list_traces()


def test_endswith_operator(tmp_path):
    traces = _traces(tmp_path)
    assert len(select(traces, "task endswith 'friday'")) == 1
    assert len(select(traces, "task endswith 'flight'")) == 1


def test_matches_operator(tmp_path):
    traces = _traces(tmp_path)
    assert len(select(traces, "task matches '^book'")) == 1
    assert len(select(traces, "task matches 'friDay'")) == 0  # case-sensitive


def test_matches_bad_regex_fails_at_parse(tmp_path):
    with pytest.raises(QueryError):
        parse("task matches '(unclosed'")


def test_matches_pattern_bound(tmp_path):
    with pytest.raises(QueryError):
        parse("task matches '" + "a" * 300 + "'")


def test_in_operator_over_scalar_field(tmp_path):
    traces = _traces(tmp_path)
    assert len(select(traces,
                      "task in ('book a flight', 'other')")) == 1
    assert len(select(traces,
                      "model in ('gpt-x', 'mini'))"[:-1])) == 2


def test_in_operator_over_set_field(tmp_path):
    traces = _traces(tmp_path)
    # "did this run ever touch any of these tools"
    picked = select(traces, "tools in ('deploy', 'rollback')")
    assert len(picked) == 1 and picked[0].task == "deploy on friday"


def test_in_single_value_still_works(tmp_path):
    traces = _traces(tmp_path)
    assert len(select(traces, "task in ('book a flight')")) == 1


def test_query_cli_door(tmp_path, capsys):
    _seed(tmp_path / "s")
    code = main(["query", "--store", str(tmp_path / "s"),
                 "tools in ('search', 'deploy')", "--json"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert isinstance(payload, list) and len(payload) == 2
