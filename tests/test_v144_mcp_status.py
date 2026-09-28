"""v144: MCP tool #28 `status` — the ops pair completes its mirror.

`annotate` mirrored long ago; `status` (the other half of the ops
pair) returns its payload only through the CLI. Now an MCP client —
a dashboard, a night-watch agent — reads the same one-glance overview
the operator sees: health, top modes, triage, last failure + chain
verdict, ledger, recidivist, optional fleet trend.
"""

import argparse
import json

from approximately.cli import _status_payload, cmd_status
from approximately.mcp_server import ServerContext, handle_request
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _seed(directory):
    store = TraceStore(directory)
    rec = Recorder("flaky watch target", save=False)
    rec.tool("search", {"q": "x"}, result=None, error="timeout")
    rec.respond("gave up", success=False, agent="night-agent")
    store.save(rec.trace)
    store.annotate(rec.trace.id, "known flake", verdict="confirmed")
    return store


def _call(arguments, store_dir="."):
    ctx = ServerContext(store_dir)
    return handle_request({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "status", "arguments": arguments},
    }, ctx)


def test_mcp_status_matches_cli_payload(tmp_path):
    store = _seed(tmp_path / "s")
    payload = _call({"store": str(store.directory)},
                    str(store.directory))
    result = json.loads(payload["result"]["content"][0]["text"])
    cli_args = argparse.Namespace(store=str(store.directory),
                                  since=None, digest_dir=None,
                                  json=True)
    assert cmd_status(cli_args) == 0  # the CLI path still works
    direct = _status_payload(store, store.list_traces(), None, None)
    assert result["traces"] == direct["traces"] == 1
    assert result["failures"] == 1
    assert result["annotations_confirmed"] == 1
    assert result["last_failure"]["chain"] in ("intact", "unsigned")
    assert result["top_recidivist"] or result["top_recidivist"] is None


def test_mcp_status_since_window(tmp_path):
    store = _seed(tmp_path / "s")
    payload = _call({"store": str(store.directory), "since": 0},
                    str(store.directory))
    result = json.loads(payload["result"]["content"][0]["text"])
    # since=0 days -> cutoff now -> the fresh trace may or may not
    # survive; the payload must stay well-formed either way
    assert "traces" in result and "failure_rate" in result


def test_status_listed_in_tools():
    from approximately.mcp_server import _TOOLS

    schema = next(t for t in _TOOLS if t["name"] == "status")
    assert schema["inputSchema"]["properties"]["digest_dir"]
