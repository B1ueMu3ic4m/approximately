"""v5946: the memory door filters by agent.

Multi-agent runs produce one conversation with several voices —
"what did the researcher actually do?" needed the query DSL or a
manual scan. ``recall --agent NAME`` filters the timeline, the
search, the summary and the digest to conversations whose named
agents match (case-insensitive substring, like --model over
models); a run with no Step.agent never matches — the
unattributed bucket stays `stats --by-agent`'s answer. The MCP
recall tool takes the same key, and the filters compose with
--grep/--day/--query across the fleet view.
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

    store = TraceStore(tmp_path / "s")
    for task, agents in (("research run", ["researcher"]),
                         ("ops run", ["deployer", "researcher"]),
                         ("solo run", [])):
        rec = Recorder(task, save=False)
        for name in agents:
            rec.tool("deploy", {}, result="ok", agent=name)
        rec.respond("done", success=True)
        store.save(rec.trace)
    return store


def test_the_timeline_keeps_the_agent_conversations(tmp_path):
    store = _seed(tmp_path)
    r = _run("--store", str(store.directory), "recall",
             "--agent", "researcher", "--json")
    payload = json.loads(r.stdout)
    tasks = sorted(e["task"] for d in payload["days"]
                   for e in d["entries"])
    assert tasks == ["ops run", "research run"], \
        "both conversations the researcher touched"
    r = _run("--store", str(store.directory), "recall",
             "--agent", "deployer", "--json")
    payload = json.loads(r.stdout)
    assert [e["task"] for d in payload["days"]
            for e in d["entries"]] == ["ops run"]


def test_matching_is_case_insensitive(tmp_path):
    store = _seed(tmp_path)
    r = _run("--store", str(store.directory), "recall",
             "--agent", "RESEARCHER")
    assert r.returncode == 0
    assert "research run" in r.stdout


def test_summary_and_digest_and_grep_compose(tmp_path):
    store = _seed(tmp_path)
    r = _run("--store", str(store.directory), "recall-summary",
             "--agent", "deployer", "--json")
    payload = json.loads(r.stdout)
    assert sum(d["conversations"] for d in payload["days"]) == 1
    r = _run("--store", str(store.directory), "recall-digest",
             "--agent", "deployer", "--json")
    assert r.returncode == 0, r.stderr
    r = _run("--store", str(store.directory), "recall", "--grep",
             "run", "--agent", "deployer", "--json")
    payload = json.loads(r.stdout)
    assert payload["hits"] == 1, \
        "the agent filter narrows the search, not just the timeline"


def test_an_unattributed_run_never_matches(tmp_path):
    store = _seed(tmp_path)
    r = _run("--store", str(store.directory), "recall",
             "--agent", "solo", "--json")
    payload = json.loads(r.stdout)
    tasks = [e["task"] for d in payload["days"]
             for e in d["entries"]]
    assert "solo run" not in tasks, (
        "a run with no Step.agent never matches: stats --by-agent "
        "answers that bucket")


def test_the_mcp_tool_gains_agent(tmp_path):
    from approximately.mcp_server import _TOOLS, ServerContext, handle_request

    recall = next(t for t in _TOOLS if t["name"] == "recall")
    assert "agent" in recall["inputSchema"]["properties"], \
        "a client cannot discover a door the schema hides"
    store = _seed(tmp_path)
    ctx = ServerContext(str(store.directory))
    payload = handle_request({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "recall",
                   "arguments": {"agent": "deployer"}},
    }, ctx)
    result = json.loads(payload["result"]["content"][0]["text"])
    assert result["conversations"] == 1
