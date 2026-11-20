"""v5922: from one conversation, the related ones.

The memory family answered "what did I talk about", "where was it
said", and "what went wrong" — but the human's follow-up in the
conversation itself is "what ELSE relates to this one?".
``recall --related TRACE_ID`` scores every other conversation:
shared tools (a Jaccard), shared task topics, the same calendar
day. The scoring is deterministic (score desc, then trace id) so
the answer never reshuffles between calls; the trace itself never
ranks; zero-score conversations never appear; each result names
the reasons its score was earned. The MCP recall tool gains the
same key (a safe id only), and the schema describes it.
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


def _convo(tmp_path, name, task, tools, *, created=None):
    from approximately.recorder import Recorder
    from approximately.store import TraceStore

    store = TraceStore(tmp_path / "s")
    rec = Recorder(task, model="m/1", store=store, save=False)
    for tool in tools:
        rec.tool(tool, {}, result="ok")
    rec.respond("done", success=True)
    if created is not None:
        rec.trace.created_at = created
    store.save(rec.trace)
    return store, rec.trace


def test_shared_tools_rank_first(tmp_path):
    _convo(tmp_path, "s", "ship the payments flow",
           ["deploy", "kubectl"])
    _convo(tmp_path, "s", "review the payments docs", ["deploy"])
    _convo(tmp_path, "s", "water the plants", ["garden_hose"],
           created=time.time() - 40 * 86400)
    store = tmp_path / "s"
    from approximately.store import TraceStore

    trace_id = TraceStore(store).list_traces()[0].id
    r = _run("--store", str(store), "recall", "--related",
             trace_id, "--json")
    payload = json.loads(r.stdout)
    tasks = [e["task"] for e in payload["results"]]
    assert tasks[0] == "review the payments docs", \
        "the conversation sharing MORE tools leads"
    assert "water the plants" not in tasks, \
        "a zero-score conversation never appears"
    assert payload["results"][0]["reasons"][0] == "shared tools"


def test_shared_topic_and_same_day_earn_reasons(tmp_path):
    now = time.time()
    _convo(tmp_path, "s", "debug the payments webhook",
           ["logs"], created=now)
    _convo(tmp_path, "s", "trace the payments webhook bug",
           ["grep"], created=now)
    from approximately.store import TraceStore

    store = tmp_path / "s"
    trace_id = TraceStore(store).list_traces()[0].id
    r = _run("--store", str(store), "recall", "--related",
             trace_id, "--json")
    payload = json.loads(r.stdout)
    top = payload["results"][0]
    assert "shared topic" in top["reasons"], \
        "the topic overlap is named"
    assert "same day" in top["reasons"], \
        "the same-day bonus is named"


def test_the_scoring_is_deterministic(tmp_path):
    _convo(tmp_path, "s", "alpha run", ["deploy"])
    _convo(tmp_path, "s", "beta run", ["deploy"])
    _convo(tmp_path, "s", "gamma run", ["deploy"])
    from approximately.store import TraceStore

    store = tmp_path / "s"
    trace_id = TraceStore(store).list_traces()[0].id
    r1 = _run("--store", str(store), "recall", "--related",
              trace_id, "--json")
    r2 = _run("--store", str(store), "recall", "--related",
              trace_id, "--json")
    assert r1.stdout == r2.stdout, \
        "equal scores break by trace id: the answer never reshuffles"


def test_related_spans_the_fleet(tmp_path):
    # the fleet view (MultiStore) delegates list_traces: the
    # scorer sees both boxes and each result names its store
    from approximately.recall import MultiStore, related
    from approximately.recorder import Recorder
    from approximately.store import TraceStore

    for name, task in (("a", "ship the payments flow"),
                       ("b", "review the payments docs")):
        store = TraceStore(tmp_path / name)
        rec = Recorder(task, model="m/1", store=store, save=False)
        rec.tool("deploy", {}, result="ok")
        rec.respond("done", success=True)
        store.save(rec.trace)

    view = MultiStore()
    view.add(TraceStore(tmp_path / "a"), str(tmp_path / "a"))
    view.add(TraceStore(tmp_path / "b"), str(tmp_path / "b"))
    trace_id = TraceStore(tmp_path / "a").list_traces()[0].id
    payload = related(view, trace_id, limit=5)
    assert payload["related"] == 1
    top = payload["results"][0]
    assert top["task"] == "review the payments docs"
    assert top["store"] == "b", \
        "a cross-box match still names its store"
    assert "shared tools" in top["reasons"]


def test_an_unknown_trace_answers_by_name(tmp_path):
    _convo(tmp_path, "s", "a run", ["deploy"])
    r = _run("--store", str(tmp_path / "s"), "recall", "--related",
             "nope01234567", "--json")
    assert r.returncode == 2, (
        "an unknown trace id is a refusal, not an empty answer")
    assert "no such trace" in r.stderr


def test_the_mcp_tool_gains_related(tmp_path):
    from approximately.mcp_server import _TOOLS, ServerContext, handle_request
    from approximately.store import TraceStore

    recall = next(t for t in _TOOLS if t["name"] == "recall")
    assert "related" in recall["inputSchema"]["properties"]
    _convo(tmp_path, "s", "ship the payments flow", ["deploy"])
    _convo(tmp_path, "s", "review the payments docs", ["deploy"])
    store = TraceStore(tmp_path / "s")
    trace_id = store.list_traces()[0].id
    ctx = ServerContext(str(tmp_path / "s"))
    payload = handle_request({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "recall",
                   "arguments": {"related": trace_id}},
    }, ctx)
    result = json.loads(payload["result"]["content"][0]["text"])
    assert result["related"] == 1
    assert result["results"][0]["task"] == "review the payments docs"
    hostile = handle_request({
        "jsonrpc": "2.0", "id": 2, "method": "tools/call",
        "params": {"name": "recall",
                   "arguments": {"related": "../../pwn"}},
    }, ctx)
    assert hostile["result"]["isError"], \
        "a path-shaped ref is refused: related names a trace id"
