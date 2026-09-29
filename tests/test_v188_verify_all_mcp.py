"""v188: MCP `verify` gains `all` — the whole-store tally over MCP.

`approximately verify --all` existed at CLI level with the six-rung
exit ladder; the MCP tool now answers the same question as data:
per-trace verdict rows plus a tally, keyed/rolled-back stores
included. `key_file` applies to every trace like the CLI's.
"""

import json

from approximately.integrity import sign
from approximately.mcp_server import ServerContext, handle_request
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _call(arguments, store_dir="."):
    ctx = ServerContext(store_dir)
    return handle_request({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "verify", "arguments": arguments},
    }, ctx)


def test_verify_all_tallies_verdicts(tmp_path):
    store = TraceStore(tmp_path / "s")
    rec = Recorder("plain run", save=False)
    rec.respond("done", success=True)
    store.save(rec.trace)
    payload = _call({"all": True, "store": str(store.directory)})
    result = json.loads(payload["result"]["content"][0]["text"])
    assert result["all"] is True
    assert result["traces"] == 1
    assert result["tally"] == {"unsigned": 1}
    assert result["rows"][0]["verdict"] == "unsigned"


def test_verify_all_with_key_file(tmp_path):
    from approximately.integrity import load_key

    key = tmp_path / "k.key"
    key.write_bytes(b"k" * 8)
    store = TraceStore(tmp_path / "s")
    rec = Recorder("signed run", save=False)
    rec.respond("done", success=True)
    sign(rec.trace, key=load_key(str(key)))
    store.save(rec.trace)
    payload = _call({"all": True, "store": str(store.directory),
                     "key_file": str(key)})
    result = json.loads(payload["result"]["content"][0]["text"])
    assert result["tally"] == {"intact": 1}


def test_schema_all_and_no_required():
    from approximately.mcp_server import _TOOLS

    schema = next(t for t in _TOOLS if t["name"] == "verify")
    assert "all" in schema["inputSchema"]["properties"]
    assert schema["inputSchema"]["required"] == []
