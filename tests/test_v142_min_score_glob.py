"""v142: precision knobs on the neighbours — and glob import over MCP.

`similar --min-score` cuts weak neighbours instead of always
returning top-N (CLI and MCP alike). `import_transcripts` grows a
`glob` parameter, so an MCP client can pull a whole directory of
dumps with the same per-file counts the CLI prints.
"""

import json

from approximately.align import similar_payload
from approximately.mcp_server import _TOOLS, ServerContext, handle_request
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _store(directory):
    store = TraceStore(directory)
    rec = Recorder("book a flight to Oslo", save=False)
    rec.tool("search", {"q": "oslo flights"}, result="3 hits")
    rec.respond("booked", success=True)
    store.save(rec.trace)
    twin = Recorder("book a flight to Oslo", save=False)
    twin.tool("search", {"q": "oslo flights"}, result="3 hits")
    twin.respond("booked", success=True)
    store.save(twin.trace)
    other = Recorder("water the plants", save=False)
    other.respond("done", success=True)
    store.save(other.trace)
    return store


def test_min_score_cuts_weak_neighbours(tmp_path):
    store = _store(tmp_path / "s")
    target = store.list_traces()[0]
    everything = similar_payload(target, store.list_traces(), top=5)
    assert len(everything["matches"]) == 2
    strict = similar_payload(target, store.list_traces(), top=5,
                             min_score=0.9)
    assert all(m["similarity"] >= 0.9 for m in strict["matches"])
    assert len(strict["matches"]) <= len(everything["matches"])


def _call(name, arguments, store_dir="."):
    ctx = ServerContext(store_dir)
    return handle_request({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    }, ctx)


def test_mcp_similar_min_score(tmp_path):
    store = _store(tmp_path / "s")
    target = store.list_traces()[0]
    payload = _call("similar", {"trace": target.id,
                                "store": str(store.directory),
                                "min_score": 0.99},
                    str(store.directory))
    result = json.loads(payload["result"]["content"][0]["text"])
    assert all(m["similarity"] >= 0.99 for m in result["matches"])
    loose = _call("similar", {"trace": target.id,
                              "store": str(store.directory)},
                  str(store.directory))
    loose_result = json.loads(loose["result"]["content"][0]["text"])
    assert len(loose_result["matches"]) >= len(result["matches"])


def test_mcp_import_transcripts_glob(tmp_path):
    for i, name in enumerate(("a.jsonl", "b.jsonl")):
        path = tmp_path / name
        path.write_text(json.dumps({"messages": [
            {"role": "user", "content": f"task {i}"},
            {"role": "assistant", "content": "ok"}]}) + "\n",
            encoding="utf-8")
    store_dir = tmp_path / "s"
    payload = _call("import_transcripts",
                    {"glob": str(tmp_path / "*.jsonl"),
                     "store": str(store_dir)},
                    str(store_dir))
    result = json.loads(payload["result"]["content"][0]["text"])
    assert result["files"] == 2
    assert result["imported"] == 2
    assert len(TraceStore(str(store_dir)).list_traces()) == 2


def test_glob_without_path_is_optional(tmp_path):
    from approximately.mcp_server import _TOOLS

    schema = next(t for t in _TOOLS
                  if t["name"] == "import_transcripts")
    assert schema["inputSchema"]["required"] == ["path"]
    assert "glob" in schema["inputSchema"]["properties"]


def test_similar_schema_has_min_score():
    schema = next(t for t in _TOOLS if t["name"] == "similar")
    assert "min_score" in schema["inputSchema"]["properties"]
