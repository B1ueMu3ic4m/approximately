"""v252: the MCP server hands over the evidence.

`evidence_pack` mirrors the CLI door (same manifest, same loud
unknown-id error), so an agent — or a reviewer's assistant — can
assemble a case without shelling out.  35 tools.
"""

import zipfile

import pytest

from approximately import mcp_server
from approximately.mcp_server import _tool_evidence_pack
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _seed(tmp_path):
    store = TraceStore(tmp_path / "s")
    rec = Recorder("case run", store=store, save=False)
    rec.respond("done", success=False)
    store.save(rec.trace)
    return store


def test_tool_lists_with_schema():
    names = {t["name"] for t in mcp_server._TOOLS}
    assert "evidence_pack" in names
    schema = next(t for t in mcp_server._TOOLS
                  if t["name"] == "evidence_pack")
    assert schema["inputSchema"]["required"] == ["trace"]


def test_tool_builds_the_same_pack(tmp_path):
    store = _seed(tmp_path)
    tid = store.list_traces()[0].id
    out = tmp_path / "case.zip"
    manifest = _tool_evidence_pack(
        mcp_server.ServerContext(str(tmp_path)),
        {"store": str(tmp_path / "s"), "trace": tid,
         "output": str(out)})
    assert manifest["chain"]["signed"] is True   # v244 auto-stamp
    with zipfile.ZipFile(out) as zf:
        assert set(zf.namelist()) == {"trace.json", "report.html",
                                      "annotations.json",
                                      "brief.md",
                                      "manifest.json"}


def test_tool_requires_trace(tmp_path):
    _seed(tmp_path)
    with pytest.raises(KeyError):
        _tool_evidence_pack(mcp_server.ServerContext(str(tmp_path)),
                            {"store": str(tmp_path / "s")})


def test_tool_unknown_trace_is_a_key_error(tmp_path):
    _seed(tmp_path)
    with pytest.raises(KeyError, match="no such trace"):
        _tool_evidence_pack(
            mcp_server.ServerContext(str(tmp_path)),
            {"store": str(tmp_path / "s"), "trace": "ghost"})


def test_default_output_names_the_trace(tmp_path):
    store = _seed(tmp_path)
    tid = store.list_traces()[0].id
    _tool_evidence_pack(mcp_server.ServerContext(str(tmp_path)),
                        {"store": str(tmp_path / "s"), "trace": tid,
                         "output": str(tmp_path / "named.zip")})
    assert (tmp_path / "named.zip").exists()
