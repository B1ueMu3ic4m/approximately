"""v242: the MCP server speaks the gate.

An agent harness (or a supervisor loop) should gate itself on the
same ceilings the CI workflow uses — without shelling out.  Two new
tools mirror the night's CLI doors: `ci_gate` returns the composed
verdict (same rows, same semantics as `approximately ci`), and
`init_gate` scaffolds the same idempotent three files.  34 tools.
"""


from approximately import mcp_server
from approximately.mcp_server import _tool_ci_gate, _tool_init_gate
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _seed(path, n_ok=4, n_bad=1, tokens=100, model="gpt-x"):
    store = TraceStore(path)
    for i in range(n_ok + n_bad):
        rec = Recorder(f"run {i}", model=model, store=store,
                       save=False)
        rec.tool("search", {"q": i}, tokens=tokens, latency_ms=100)
        rec.respond("done", success=i < n_ok)
        store.save(rec.trace)
    return store


def test_tools_listed_with_schemas():
    names = {t["name"] for t in mcp_server._TOOLS}
    assert {"ci_gate", "init_gate"} <= names
    ci = next(t for t in mcp_server._TOOLS if t["name"] == "ci_gate")
    props = ci["inputSchema"]["properties"]
    assert "max_failure_rate" in props and "prices" in props


def test_ci_gate_passes_a_healthy_store(tmp_path):
    _seed(tmp_path / "s", n_ok=9, n_bad=1)
    out = _tool_ci_gate(mcp_server.ServerContext(str(tmp_path)),
                        {"store": str(tmp_path / "s"),
                         "max_failure_rate": 0.2})
    assert out["ok"] is True and out["traces"] == 10
    gates = {g["gate"]: g for g in out["gates"]}
    assert gates["failure-rate"]["value"] == 0.1
    assert gates["min-traces"]["ok"] is True


def test_ci_gate_breaches_and_explains(tmp_path):
    _seed(tmp_path / "s", n_ok=1, n_bad=3)
    out = _tool_ci_gate(mcp_server.ServerContext(str(tmp_path)),
                        {"store": str(tmp_path / "s"),
                         "max_failure_rate": 0.5})
    assert out["ok"] is False


def test_ci_gate_spend_needs_prices(tmp_path):
    _seed(tmp_path / "s")
    try:
        _tool_ci_gate(mcp_server.ServerContext(str(tmp_path)),
                      {"store": str(tmp_path / "s"),
                       "max_spend": 1.0})
    except KeyError as exc:
        assert "prices" in str(exc)
    else:
        raise AssertionError("spend gate accepted without prices")


def test_ci_gate_spend_fails_unpriced_models(tmp_path):
    # the CLI contract carries over: a budget you cannot compute
    # does not hold
    _seed(tmp_path / "s", model="mystery-1")
    out = _tool_ci_gate(
        mcp_server.ServerContext(str(tmp_path)),
        {"store": str(tmp_path / "s"), "max_spend": 10_000.0,
         "prices": {"gpt-x": 3.0}})
    assert out["ok"] is False


def test_ci_gate_empty_store_is_a_loud_error(tmp_path):
    TraceStore(tmp_path / "s")
    try:
        _tool_ci_gate(mcp_server.ServerContext(str(tmp_path)),
                      {"store": str(tmp_path / "s"),
                       "max_tokens": 10})
    except KeyError as exc:
        assert "empty" in str(exc)
    else:
        raise AssertionError("empty store gated silently")


def test_ci_gate_no_ceilings_is_a_configuration_error(tmp_path):
    _seed(tmp_path / "s")
    try:
        _tool_ci_gate(mcp_server.ServerContext(str(tmp_path)),
                      {"store": str(tmp_path / "s")})
    except KeyError as exc:
        assert "ceilings" in str(exc)
    else:
        raise AssertionError("zero ceilings gated silently")


def test_init_gate_tool_scaffolds_idempotently(tmp_path):
    ctx = mcp_server.ServerContext(str(tmp_path))
    first = _tool_init_gate(ctx, {"directory": str(tmp_path)})
    assert set(first["files"].values()) == {"written"}
    again = _tool_init_gate(ctx, {"directory": str(tmp_path)})
    assert set(again["files"].values()) == {"skipped"}
    wf = tmp_path / ".github" / "workflows" / "agent-gate.yml"
    assert "approximately ci" in wf.read_text(encoding="utf-8")
