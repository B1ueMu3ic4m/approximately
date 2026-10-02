"""v254: the MCP server runs the comparison.

`compare` as a tool: an agent (or a deploy bot's assistant) asks
"did this deployment get worse?" without shelling out — same
verdict, structured.  `fail_on_new_modes` maps to the CLI gate's
exit code, surfaced as `ok: false`.  36 tools.
"""


import pytest

from approximately import mcp_server
from approximately.mcp_server import _tool_compare
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _seed(path, deploy_fail=False, n_ok=3):
    store = TraceStore(path)
    for i in range(n_ok):
        rec = Recorder(f"run {i}", model="gpt-x", store=store,
                       save=False)
        rec.tool("search", {"q": i}, tokens=100, latency_ms=100)
        rec.respond("done", success=True)
        store.save(rec.trace)
    if deploy_fail:
        rec = Recorder("deploy fail", model="gpt-x", store=store,
                       save=False)
        rec.tool("deploy", {"env": "prod"}, tokens=50,
                 latency_ms=200)
        rec.tool("deploy", {"env": "prod"}, tokens=50,
                 latency_ms=200)
        rec.respond("rolled back", success=False)
        store.save(rec.trace)
    return store


def test_tool_lists_with_schema():
    names = {t["name"] for t in mcp_server._TOOLS}
    assert "compare" in names


def test_tool_sees_no_regression(tmp_path):
    _seed(tmp_path / "base", deploy_fail=True)
    _seed(tmp_path / "cand", deploy_fail=True)
    out = _tool_compare(mcp_server.ServerContext(str(tmp_path)),
                        {"baseline": str(tmp_path / "base"),
                         "candidate": str(tmp_path / "cand")})
    assert out["ok"] is True and out["new_modes"] == []
    assert out["baseline"]["traces"] == 4


def test_tool_flags_the_new_mode_and_fails(tmp_path):
    _seed(tmp_path / "base")
    _seed(tmp_path / "cand", deploy_fail=True)
    out = _tool_compare(
        mcp_server.ServerContext(str(tmp_path)),
        {"baseline": str(tmp_path / "base"),
         "candidate": str(tmp_path / "cand"),
         "fail_on_new_modes": True})
    assert out["ok"] is False and out["new_modes"] == ["FM-1.3"]


def test_tool_prices_bridge(tmp_path):
    _seed(tmp_path / "base", n_ok=1)
    _seed(tmp_path / "cand", n_ok=3)
    out = _tool_compare(
        mcp_server.ServerContext(str(tmp_path)),
        {"baseline": str(tmp_path / "base"),
         "candidate": str(tmp_path / "cand"),
         "prices": {"gpt-x": 2.0}})
    assert out["spend"]["baseline"] == 0.2
    assert out["spend"]["candidate"] == 0.6


def test_tool_requires_both_stores(tmp_path):
    _seed(tmp_path / "base")
    with pytest.raises(KeyError):
        _tool_compare(mcp_server.ServerContext(str(tmp_path)),
                      {"baseline": str(tmp_path / "base")})


def test_tool_rejects_junk_prices(tmp_path):
    _seed(tmp_path / "base")
    _seed(tmp_path / "cand")
    with pytest.raises(KeyError, match="non-negative"):
        _tool_compare(mcp_server.ServerContext(str(tmp_path)),
                      {"baseline": str(tmp_path / "base"),
                       "candidate": str(tmp_path / "cand"),
                       "prices": {"gpt-x": "free, pretty please"}})
