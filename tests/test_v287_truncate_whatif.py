"""Night VII, round 6: the truncation what-if, and agents get the
composition view.

``context --composition --truncate-results N`` answers the sizing
question for truncation rules: if every tool result longer than N
characters were cut there, how many tokens does the window save?
The MCP context tool gains the same two knobs.
"""


from approximately.cli import main
from approximately.context import composition
from approximately.mcp_server import (
    _TOOLS,
    ServerContext,
    _tool_context,
)
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _store(tmp_path):
    store = TraceStore(tmp_path / "s")
    with Recorder("bloaty", model="m/1", store=store,
                  save=False) as rec:
        rec.tool("search", {"q": 1}, result="x" * 8_000)
        rec.tool("compare", {"q": 2}, result="y" * 800)
        rec.respond("done", success=True)
    store.save(rec.trace)
    return store, rec.trace


def test_truncation_what_if_counts_savings(tmp_path):
    _, trace = _store(tmp_path)
    plain = composition(trace)
    whatif = composition(trace, truncate_results=1_000)
    assert whatif["tokens_saved"] > 0
    assert whatif["tokens_after"] < plain["total_tokens"]
    assert whatif["tokens_before"] == plain["total_tokens"]
    # the 800-char result is untouched by a 1,000-char cut
    assert whatif["tokens_saved"] < whatif["tokens_before"]


def test_truncation_below_everything_saves_nothing(tmp_path):
    _, trace = _store(tmp_path)
    whatif = composition(trace, truncate_results=100_000)
    assert whatif["tokens_saved"] == 0
    assert whatif["tokens_after"] == whatif["tokens_before"]


def test_cli_reports_the_savings(tmp_path, capsys):
    store, trace = _store(tmp_path)
    rc = main(["context", trace.id, "--store", str(store.directory),
               "--composition", "--truncate-results", "1_000"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "truncating tool results at 1,000 chars" in out
    assert "saved" in out


def test_mcp_context_gains_both_knobs(tmp_path):
    store, trace = _store(tmp_path)
    ctx = ServerContext(str(store.directory))
    tool = next(t for t in _TOOLS if t["name"] == "context")
    props = tool["inputSchema"]["properties"]
    assert "composition" in props and "truncate_results" in props
    payload = _tool_context(ctx, {"store": str(store.directory),
                                  "trace": trace.id,
                                  "composition": True,
                                  "truncate_results": 1_000})
    assert payload["tokens_saved"] > 0
