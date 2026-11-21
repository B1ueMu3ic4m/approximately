"""v5933: the memory doors speak the query DSL.

The memory family had outcome filters (--failed-only/--ok-only),
a model substring and calendar windows — but "which conversations
touched deploy and failed with a slow tool" needed the export door.
``--query EXPR`` wraps the resolved view (one store or the fleet)
with the shared query DSL: every memory door — timeline, search,
summary, digest, related — then reads the selection, not the whole
box, composing with the existing filters. The expression compiles
once per door call; a malformed one is refused by name, and the
MCP recall tool gains the same key with the same refusals on the
wire.
"""

import json
import subprocess
import sys
import time
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

    for name, task, ok, age in (
            ("a", "ship payments flow", False, 600),
            ("b", "water plants daily", True, 3 * 86400)):
        store = TraceStore(tmp_path / name)
        rec = Recorder(task, model="m/1", store=store, save=False)
        rec.tool("deploy", {}, result="ok")
        rec.respond("done", success=ok)
        rec.trace.created_at = time.time() - age
        store.save(rec.trace)


def test_the_timeline_reads_the_selection(tmp_path):
    _seed(tmp_path)
    r = _run("--store", str(tmp_path / "a"), "recall", "--query",
             "success == false and created > 24h ago", "--json")
    assert r.returncode == 0, r.stderr
    payload = json.loads(r.stdout)
    assert payload["conversations"] == 1, \
        "the time-word expression carries into the memory door"
    tasks = [e["task"] for day in payload["days"]
             for e in day["entries"]]
    assert tasks == ["ship payments flow"]


def test_summary_and_digest_filter_alike(tmp_path):
    _seed(tmp_path)
    r = _run("--store", str(tmp_path / "a"), "recall-summary",
             "--query", "success == false", "--json")
    assert r.returncode == 0, r.stderr
    payload = json.loads(r.stdout)
    assert sum(day["conversations"] for day in payload["days"]) == 1, \
        "the summary counts the selection, not the box"
    r = _run("--store", str(tmp_path / "a"), "recall-digest",
             "--query", "success == false", "--json")
    assert r.returncode == 0, r.stderr


def test_the_query_spans_the_fleet(tmp_path):
    _seed(tmp_path)
    r = _run("recall", str(tmp_path / "a"), str(tmp_path / "b"),
             "--query", "success == true", "--json")
    assert r.returncode == 0, r.stderr
    payload = json.loads(r.stdout)
    assert payload["conversations"] == 1, \
        "the ok trace lives in box b: the wrap reaches across boxes"
    tasks = [e["task"] for day in payload["days"]
             for e in day["entries"]]
    assert tasks == ["water plants daily"]


def test_query_composes_with_grep(tmp_path):
    _seed(tmp_path)
    both = _run("--store", str(tmp_path / "a"), "recall", "--grep",
                "payments", "--query", "success == false", "--json")
    assert json.loads(both.stdout)["hits"] == 1
    only_grep = _run("--store", str(tmp_path / "a"), "recall",
                     "--grep", "payments", "--query",
                     "success == true", "--json")
    assert json.loads(only_grep.stdout)["hits"] == 0, \
        "the DSL filter narrows the search, not just the timeline"


def test_a_malformed_expression_is_refused_by_name(tmp_path):
    _seed(tmp_path)
    for expr, needle in (("tokens > 5m ago", "apply to"),
                         ("created > 24q ago",
                          "unknown duration unit")):
        r = _run("--store", str(tmp_path / "a"), "recall",
                 "--query", expr)
        assert r.returncode != 0, expr
        assert needle in r.stderr, expr


def test_the_mcp_tool_gains_query(tmp_path):
    from approximately.mcp_server import _TOOLS, ServerContext, handle_request

    recall = next(t for t in _TOOLS if t["name"] == "recall")
    assert "query" in recall["inputSchema"]["properties"], \
        "a client cannot discover a door the schema hides"
    _seed(tmp_path)
    ctx = ServerContext(str(tmp_path / "a"))
    payload = handle_request({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "recall",
                   "arguments": {"query": "success == false"}},
    }, ctx)
    result = json.loads(payload["result"]["content"][0]["text"])
    assert result["conversations"] == 1
    hostile = handle_request({
        "jsonrpc": "2.0", "id": 2, "method": "tools/call",
        "params": {"name": "recall",
                   "arguments": {"query": "created > 24q ago"}},
    }, ctx)
    assert hostile["result"]["isError"]
    assert "unknown duration unit" in \
        hostile["result"]["content"][0]["text"]
