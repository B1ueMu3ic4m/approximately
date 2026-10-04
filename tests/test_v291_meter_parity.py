"""Night VII, round 12: the meters meet parity.

The MCP ``anomalies`` tool meters results (``results: true``), and
the CLI's ``--per-tool`` now works for the result meter too — every
meter carries every option the family shares.
"""


from approximately.anomaly import detect_result_anomalies
from approximately.cli import main
from approximately.mcp_server import (
    _TOOLS,
    ServerContext,
    _tool_anomalies,
)
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _noisy(tmp_path):
    store = TraceStore(tmp_path / "s")
    with Recorder("mixed tools", model="m/1", store=store,
                  save=False) as rec:
        for i in range(5):
            rec.tool("search", {"i": i}, result="x" * 200)
            rec.tool("fetch", {"i": i}, result="y" * 150)
        rec.tool("fetch", {}, result="z" * 20_000)
        rec.respond("done", success=True)
    store.save(rec.trace)
    return store, rec.trace


def test_result_meter_per_tool_isolates_families(tmp_path):
    _, trace = _noisy(tmp_path)
    scoped = detect_result_anomalies(trace, per_tool=True)
    # pooled, the 20k wall towers over everything; scoped to the
    # fetch family, it still towers — but the tool attribution is
    # exact and the smaller family scale cannot mask it
    assert {a.tool for a in scoped} == {"fetch"}
    assert any(a.result_chars == 20_000 for a in scoped)


def test_mcp_anomalies_results_fleet(tmp_path):
    store, _ = _noisy(tmp_path)
    payload = _tool_anomalies(ServerContext(str(store.directory)),
                              {"store": str(store.directory),
                               "results": True, "fleet": True})
    assert payload["results"] is True
    assert payload["fleet"] is True
    assert payload["isError"] is True
    assert payload["count"] >= 1


def test_mcp_anomalies_results_single_trace(tmp_path):
    store, trace = _noisy(tmp_path)
    payload = _tool_anomalies(ServerContext(str(store.directory)),
                              {"store": str(store.directory),
                               "trace": trace.id,
                               "results": True})
    assert payload["results"] is True
    assert any(a["tool"] == "fetch" and a["result_chars"] == 20_000
               for a in payload["anomalies"])


def test_mcp_schema_declares_results():
    tool = next(t for t in _TOOLS if t["name"] == "anomalies")
    assert "results" in tool["inputSchema"]["properties"]


def test_cli_results_per_tool(tmp_path, capsys):
    store, _ = _noisy(tmp_path)
    rc = main(["anomalies", "latest", "--store",
               str(store.directory), "--results", "--per-tool"])
    out = capsys.readouterr().out
    assert rc == 1
    assert "fetch" in out
