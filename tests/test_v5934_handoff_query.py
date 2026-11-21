"""v5934: the worklist and the aggregate speak the query DSL.

The postmortem worklist orders itself (unannotated failures
first) and the stats door counted the whole box — but "annotate
the FM-3.2 ones first" or "the aggregate of just the slow
failures" needed the export door. ``handoff --queue N --query
EXPR`` narrows the worklist to the failures matching the shared
expression (fleet boxes included, unreadable rows never hidden —
a filter narrows evidence, it does not launder it), and ``stats
--query EXPR`` aggregates the selection instead of the whole box,
matching the wire, where the stats tool already took an
expression. ``--query`` without ``--queue`` is refused by name.
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


def _seed(tmp_path):
    from approximately.recorder import Recorder
    from approximately.store import TraceStore

    store = TraceStore(tmp_path / "a")
    for task, ok, tool, lat in (
            ("slow search failure", False, "search", 6000),
            ("slow deploy failure", False, "deploy", 6000),
            ("fast ok run", True, "search", 100)):
        rec = Recorder(task, model="m/1", store=store, save=False)
        rec.tool(tool, {}, result="ok", latency_ms=lat)
        rec.respond("done", success=ok)
        store.save(rec.trace)
    other = TraceStore(tmp_path / "b")
    rec = Recorder("slow other failure", model="m/1",
                   store=other, save=False)
    rec.tool("search", {}, result=None, error="boom")
    rec.respond("done", success=False)
    other.save(rec.trace)


def test_the_worklist_narrows_by_expression(tmp_path):
    _seed(tmp_path)
    everything = _run("--store", str(tmp_path / "a"), "handoff",
                      "--queue", "5")
    assert "slow search failure" in everything.stdout
    assert "slow deploy failure" in everything.stdout
    narrowed = _run("--store", str(tmp_path / "a"), "handoff",
                    "--queue", "5", "--query",
                    "tools contains 'deploy'")
    assert "slow deploy failure" in narrowed.stdout
    assert "slow search failure" not in narrowed.stdout, \
        "the DSL narrows the queue, not just the page title"
    slow = _run("--store", str(tmp_path / "a"), "handoff",
                "--queue", "5", "--query", "max_latency > 5000")
    assert "slow search failure" in slow.stdout, \
        "a derived field drives the triage order too"


def test_the_query_spans_the_fleet_worklist(tmp_path):
    _seed(tmp_path)
    r = _run("handoff", "--queue", "5",
             str(tmp_path / "a"), str(tmp_path / "b"), "--query",
             "tools contains 'deploy'")
    assert "(fleet)" in r.stdout
    assert "slow other failure" not in r.stdout, \
        "box b's search failure is outside the selection"
    r = _run("handoff", "--queue", "5",
             str(tmp_path / "a"), str(tmp_path / "b"), "--query",
             "tools contains 'search'")
    assert "slow other failure" in r.stdout


def test_query_without_queue_is_refused_by_name(tmp_path):
    _seed(tmp_path)
    r = _run("--store", str(tmp_path / "a"), "handoff", "--query",
             "success == false")
    assert r.returncode == 2
    assert "--query works with --queue" in r.stderr
    r = _run("--store", str(tmp_path / "a"), "handoff", "--queue",
             "3", "--query", "created > 24q ago")
    assert r.returncode != 0
    assert "unknown duration unit" in r.stderr, \
        "a malformed expression is refused by name too"


def test_stats_aggregates_the_selection(tmp_path):
    _seed(tmp_path)
    r = _run("--store", str(tmp_path / "a"), "stats", "--query",
             "success == false", "--json")
    payload = json.loads(r.stdout)
    assert payload["traces"] == 2, \
        "the aggregate reads the selection, not the box"
    assert payload["failure_rate"] == 1.0
    r = _run("--store", str(tmp_path / "a"), "stats", "--query",
             "success == true", "--json")
    assert json.loads(r.stdout)["traces"] == 1
    r = _run("--store", str(tmp_path / "a"), "stats", "--query",
             "success >")
    assert r.returncode != 0
    assert "expected" in r.stderr


def test_the_mcp_tool_gains_queue_query(tmp_path):
    from approximately.mcp_server import _TOOLS, ServerContext, handle_request

    handoff = next(t for t in _TOOLS if t["name"] == "handoff")
    assert "query" in handoff["inputSchema"]["properties"], \
        "a client cannot discover a door the schema hides"
    _seed(tmp_path)
    ctx = ServerContext(str(tmp_path / "a"))
    payload = handle_request({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "handoff",
                   "arguments": {"queue": 5,
                                 "query": "tools contains "
                                          "'deploy'"}},
    }, ctx)
    result = json.loads(payload["result"]["content"][0]["text"])
    assert "slow deploy failure" in result["markdown"]
    assert "slow search failure" not in result["markdown"]
    hostile = handle_request({
        "jsonrpc": "2.0", "id": 2, "method": "tools/call",
        "params": {"name": "handoff",
                   "arguments": {"queue": 3,
                                 "query": "created > 24q ago"}},
    }, ctx)
    assert hostile["result"]["isError"]
    assert "unknown duration unit" in \
        hostile["result"]["content"][0]["text"]
