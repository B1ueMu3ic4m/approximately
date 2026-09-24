"""v94: the recidivist filter — agent_scorecard(min_failed=...) and its
three surfaces.

One flaky run is noise; a repeat offender is a fleet problem. The
filter lives in the library so CLI (``stats --by-agent --min-failed``)
and MCP (``scoreboard.min_failed``) stay in lockstep, and the MCP
handshake stops advertising a hardcoded version that went stale at
0.37.
"""

import json

from approximately.cli import build_parser
from approximately.cluster import UNATTRIBUTED, agent_scorecard
from approximately.mcp_server import SERVER_INFO, ServerContext, handle_request
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _crew_store(tmp_path):
    """lead touches 2 failed traces (recidivist), worker 1 failed,
    solo only ever succeeds."""
    store = TraceStore(str(tmp_path / "s"))
    for i, ok in enumerate([False, False]):
        rec = Recorder(f"lead run {i}", save=False)
        rec.tool("search", {"q": str(i)}, result="y", agent="lead",
                 error=None if ok else "timeout")
        rec.respond("done", success=ok, agent="lead")
        store.save(rec.trace)
    rec = Recorder("worker run", save=False)
    rec.tool("bash", {"cmd": "ls"}, result="y", agent="worker",
             error="boom")
    rec.respond("done", success=False, agent="worker")
    store.save(rec.trace)
    solo = Recorder("solo run", save=False)
    solo.respond("fine", agent="solo", success=True)
    store.save(solo.trace)
    return store


def test_min_failed_none_keeps_all(tmp_path):
    rows = agent_scorecard(_crew_store(tmp_path).list_traces())
    assert {r["agent"] for r in rows} == {"lead", "worker", "solo"}


def test_min_failed_one_drops_clean_agents(tmp_path):
    rows = agent_scorecard(_crew_store(tmp_path).list_traces(),
                           min_failed=1)
    assert {r["agent"] for r in rows} == {"lead", "worker"}
    assert all(r["failed_traces"] >= 1 for r in rows)


def test_min_failed_two_is_recidivist_only(tmp_path):
    rows = agent_scorecard(_crew_store(tmp_path).list_traces(),
                           min_failed=2)
    assert [r["agent"] for r in rows] == ["lead"]
    assert rows[0]["failed_traces"] == 2


def test_min_failed_impossible_keeps_nothing(tmp_path):
    rows = agent_scorecard(_crew_store(tmp_path).list_traces(),
                           min_failed=99)
    assert rows == []


def test_mcp_scoreboard_min_failed(tmp_path):
    store = _crew_store(tmp_path)
    resp = handle_request({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "scoreboard", "arguments": {
            "store": str(store.directory), "min_failed": 2}},
    }, ServerContext("."))
    assert resp["result"]["isError"] is False
    payload = json.loads(resp["result"]["content"][0]["text"])
    assert [r["agent"] for r in payload["agents"]] == ["lead"]
    assert payload["traces_scanned"] == 4


def test_cli_stats_min_failed(tmp_path, capsys):
    store = _crew_store(tmp_path)
    parser = build_parser()
    args = parser.parse_args(["stats", "--store", str(store.directory),
                              "--by-agent", "--min-failed", "2",
                              "--json"])
    assert args.func(args) == 0
    rows = json.loads(capsys.readouterr().out)
    assert [r["agent"] for r in rows] == ["lead"]

    args = parser.parse_args(["stats", "--store", str(store.directory),
                              "--by-agent", "--min-failed", "99"])
    assert args.func(args) == 0
    assert UNATTRIBUTED not in capsys.readouterr().out


def test_server_info_tracks_installed_version():
    from importlib import metadata

    assert SERVER_INFO["version"] == metadata.version("approximately")
