"""v5931: the query DSL reads time the way a human writes it.

``created > 1763692800`` was the only way to ask "what failed in
the last day" — an epoch on the command line, which nobody writes
from memory. Time words fix that: ``created > 24h ago`` (units
s/m/h/d/w, floats fine, case-insensitive). The clock is read once
per parse, not per trace, so one select has one consistent "now".
A unit-shaped word that is not a unit, and a duration on a field
where it cannot mean anything (``tokens > 5m ago``), are refused
by name; a trailing unit without ``ago`` stays the leftover error
it always was.
"""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _run(*args):
    return subprocess.run(
        [sys.executable, "-m", "approximately", *args],
        capture_output=True, text=True, cwd=str(ROOT),
        encoding="utf-8")


def _convo(tmp_path, task, age_s, *, ok=True):
    import time

    from approximately.recorder import Recorder
    from approximately.store import TraceStore

    store = TraceStore(tmp_path / "s")
    rec = Recorder(task, model="m/1", store=store, save=False)
    rec.tool("deploy", {}, result="ok")
    rec.respond("done", success=ok)
    rec.trace.created_at = time.time() - age_s
    store.save(rec.trace)
    return rec.trace


def _seed(tmp_path):
    return (_convo(tmp_path, "fresh ok run", 600),
            _convo(tmp_path, "old failed run", 3 * 86400, ok=False))


def test_the_window_matches_what_a_human_means(tmp_path):
    _seed(tmp_path)
    r = _run("--store", str(tmp_path / "s"), "query",
             "created > 24h ago")
    assert r.returncode == 0, r.stderr
    assert "fresh ok run" in r.stdout, "the recent trace is in"
    assert "old failed run" not in r.stdout, \
        "three days back is outside the day window"


def test_units_scale_and_compose(tmp_path):
    from approximately.query import parse

    fresh, old = _seed(tmp_path)
    assert not parse("created > 5m ago")(fresh), \
        "a 10-minute-old trace is not in the last 5 minutes"
    assert parse("created > 1.5w ago")(old), \
        "float durations and weeks both work"
    failed_recent = parse(
        "success == false and created > 24h ago")
    failed_ever = parse("success == false")
    fresh_failed = _convo(tmp_path, "recent failure", 300, ok=False)
    assert failed_recent(fresh_failed)
    assert not failed_recent(fresh), \
        "the AND carries the time bound into the composition"
    assert failed_ever(old), \
        "without time words the old failure still shows"


def test_case_insensitive(tmp_path):
    from approximately.query import parse

    fresh, _ = _seed(tmp_path)
    assert parse("created > 24H AGO")(fresh), \
        "the words read the same in any case"


def test_an_unknown_unit_fails_by_name(tmp_path):
    from approximately.query import QueryError, parse

    try:
        parse("created > 24q ago")
    except QueryError as exc:
        assert "unknown duration unit 'q'" in str(exc)
        assert "s, m, h, d, w" in str(exc), \
            "the refusal lists the units a human can use"
    else:
        raise AssertionError("an invented unit must not parse")
    r = _run("--store", str(tmp_path / "s"), "query",
             "created > 24q ago")
    assert r.returncode != 0
    assert "unknown duration unit" in r.stderr


def test_time_words_refused_on_other_fields(tmp_path):
    from approximately.query import QueryError, parse

    for expr in ("tokens > 5m ago", "steps > 1d ago"):
        try:
            parse(expr)
        except QueryError as exc:
            assert "apply to 'created'" in str(exc), \
                f"{expr}: the typo is named, not silently misrun"
        else:
            raise AssertionError(f"{expr} must not parse")


def test_a_trailing_unit_without_ago_stays_a_leftover(tmp_path):
    from approximately.query import QueryError, parse

    try:
        parse("created > 24h")
    except QueryError as exc:
        assert "unexpected 'h'" in str(exc), \
            "no ago, no time words: the old refusal stands"
    else:
        raise AssertionError("a bare unit must not parse")


def test_the_mcp_tool_sells_and_answers(tmp_path):
    from approximately.mcp_server import _TOOLS, ServerContext, handle_request

    query = next(t for t in _TOOLS if t["name"] == "query")
    assert "ago" in query["description"], \
        "a client cannot discover time words the schema hides"
    _seed(tmp_path)
    ctx = ServerContext(str(tmp_path / "s"))
    payload = handle_request({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "query",
                   "arguments": {
                       "expression": "created > 24h ago"}},
    }, ctx)
    result = json.loads(payload["result"]["content"][0]["text"])
    assert result["count"] == 1, \
        "the wire answers the human window like the door"
    hostile = handle_request({
        "jsonrpc": "2.0", "id": 2, "method": "tools/call",
        "params": {"name": "query",
                   "arguments": {
                       "expression": "created > 24q ago"}},
    }, ctx)
    assert hostile["result"]["isError"]
    assert "unknown duration unit" in \
        hostile["result"]["content"][0]["text"]
