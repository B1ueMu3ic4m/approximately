"""v113: per-tool rollup — the action-side twin of the agent
scorecard.

`stats --by-tool` and MCP `scoreboard {group_by: "tool"}` ask the
tool question: which tools attract the errors, and which ones show up
in failing runs? Participation, not proven causation — the same
honesty contract as the agent scorecard.
"""

import json

from approximately.cli import build_parser
from approximately.cluster import tool_scorecard
from approximately.mcp_server import ServerContext, handle_request
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _store(tmp_path):
    store = TraceStore(str(tmp_path / "s"))
    for i in range(2):  # two failing runs touching deploy + search
        rec = Recorder(f"fail {i}", save=False)
        rec.tool("search", {"q": i}, result="none", agent="a")
        rec.tool("deploy", {"env": "prod"}, result=None,
                 error="timeout", agent="a")
        rec.respond("gave up", success=False, agent="a")
        store.save(rec.trace)
    rec = Recorder("pass", save=False)
    rec.tool("search", {"q": 9}, result="hit")
    rec.respond("done", success=True)
    store.save(rec.trace)
    return store


def _call(arguments):
    return handle_request({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "scoreboard", "arguments": arguments},
    }, ServerContext("."))


def test_library_rollup(tmp_path):
    rows = tool_scorecard(_store(tmp_path).list_traces())
    by_tool = {r["tool"]: r for r in rows}
    assert by_tool["deploy"]["steps"] == 2
    assert by_tool["deploy"]["errors"] == 2
    assert by_tool["deploy"]["failure_rate"] == 1.0
    assert by_tool["search"]["traces"] == 3
    assert by_tool["search"]["failure_rate"] == round(2 / 3, 3)


def test_cli_by_tool(tmp_path, capsys):
    store = _store(tmp_path)
    parser = build_parser()
    args = parser.parse_args(["stats", "--store", str(store.directory),
                              "--by-tool", "--json"])
    assert args.func(args) == 0
    rows = json.loads(capsys.readouterr().out)
    assert {r["tool"] for r in rows} == {"search", "deploy"}


def test_mcp_group_by_tool(tmp_path):
    store = _store(tmp_path)
    resp = _call({"store": str(store.directory), "group_by": "tool"})
    assert resp["result"]["isError"] is False
    payload = json.loads(resp["result"]["content"][0]["text"])
    tools = [r["tool"] for r in payload["agents"]]
    assert set(tools) == {"search", "deploy"}
    assert payload["traces_scanned"] == 3


def test_mcp_default_group_is_agent(tmp_path):
    store = _store(tmp_path)
    resp = _call({"store": str(store.directory)})
    payload = json.loads(resp["result"]["content"][0]["text"])
    assert "agent" in payload["agents"][0]
