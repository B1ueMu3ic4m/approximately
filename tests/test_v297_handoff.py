"""v297: the handoff brief — what the next engineer actually reads.

One markdown page composed from the store: what failed and why we
think so, whether the chain is trustworthy, the burn at the price
catalog, the annotation trail, and where the full record lives.
``--redact`` renders the page from a sanitized view, so it is safe
to paste before it exists.
"""

import argparse
import contextlib
import io
import json

import pytest

from approximately.cli import cmd_handoff
from approximately.handoff import brief
from approximately.mcp_server import ServerContext, _tool_handoff
from approximately.redact import compile_patterns
from approximately.store import TraceStore
from approximately.trace import Step, Trace


def _failed(store, secret=True):
    t = Trace(task="rotate the api key", model="gpt-x")
    t.add(Step(kind="tool_call", tool="sh", result="planning",
               tokens=1200, latency_ms=800))
    err = "AKIAIOSFODNN7EXAMPLE rejected: 403" if secret \
        else "rejected: 403"
    t.add(Step(kind="tool_call", tool="sh", error=err,
               tokens=900, latency_ms=400))
    t.success = False
    store.save(t)
    return t


def test_brief_sections(tmp_path):
    store = TraceStore(tmp_path)
    t = _failed(store)
    store.annotate(t.id, "dup of yesterday", verdict="confirmed")
    page = brief(t, store)
    assert page.startswith("# Handoff: rotate the api key")
    assert "outcome: FAILED" in page
    assert "2,100 tokens" in page
    assert "hash chain: intact" in page
    assert "annotations: 1 on file" in page and "[confirmed]" in page
    assert "## What failed" in page
    assert "step #1" in page and "rejected: 403" in page
    assert "attribution:" in page
    assert f"Full record: `{tmp_path}/{t.id}.json`" in page


def test_brief_cost_from_catalog(tmp_path):
    from approximately.prices import set_rate

    store = TraceStore(tmp_path)
    t = _failed(store)
    set_rate(tmp_path, "gpt-x", 0.5)  # 2100 tokens -> $1.05
    page = brief(t, store)
    assert "~$1.0500 at the store catalog" in page
    t2 = Trace(task="unpriced model", model="mystery-x")
    t2.add(Step(kind="tool_call", tool="sh", tokens=500))
    t2.success = True
    store.save(t2)
    page2 = brief(t2, store)
    assert "at the store catalog" not in page2  # honestly absent


def test_brief_redaction_scrubs_every_line(tmp_path):
    store = TraceStore(tmp_path)
    t = _failed(store)
    table = compile_patterns()
    page = brief(t, store, table=table)
    assert "AKIAIOSFODNN7EXAMPLE" not in page
    assert "[REDACTED:aws_key]" in page
    # the record path never carried secrets
    assert f"{tmp_path}/{t.id}.json" in page


def test_brief_passing_run_and_corrupt_catalog(tmp_path):
    store = TraceStore(tmp_path)
    t = Trace(task="fine run", model="m")
    t.add(Step(kind="tool_call", tool="sh", result="ok"))
    t.success = True
    store.save(t)
    page = brief(t, store)
    assert "nothing — this run passed" in page
    (tmp_path / "prices.json").write_text("{bad", encoding="utf-8")
    page2 = brief(t, store)  # corrupt catalog: unpriced, not fatal
    assert "outcome:" in page2


def test_cli_stdout_out_and_json(tmp_path, capsys):
    store = TraceStore(tmp_path)
    t = _failed(store)
    args = argparse.Namespace(store=str(tmp_path), trace=t.id,
                              redact=False, out=None,
                              **{"json": False})
    assert cmd_handoff(args) == 0
    assert "# Handoff:" in capsys.readouterr().out
    out = tmp_path / "brief.md"
    args = argparse.Namespace(store=str(tmp_path), trace=t.id,
                              redact=False, out=str(out),
                              **{"json": False})
    assert cmd_handoff(args) == 0
    assert out.read_text(encoding="utf-8").startswith("# Handoff:")
    args = argparse.Namespace(store=str(tmp_path), trace=t.id,
                              redact=True, out=None,
                              **{"json": True})
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        assert cmd_handoff(args) == 0
    payload = json.loads(buf.getvalue())
    assert payload["redacted"] is True
    assert "AKIAIOSFODNN7EXAMPLE" not in payload["markdown"]


def test_cli_unknown_trace(tmp_path, capsys):
    TraceStore(tmp_path)
    args = argparse.Namespace(store=str(tmp_path), trace="ghost",
                              redact=False, out=None,
                              **{"json": False})
    assert cmd_handoff(args) == 2
    capsys.readouterr()


def test_mcp_handoff(tmp_path):
    store = TraceStore(tmp_path)
    t = _failed(store)
    payload = _tool_handoff(ServerContext(str(tmp_path)),
                            {"trace": t.id})
    assert payload["trace"] == t.id
    assert payload["redacted"] is False
    assert "## What failed" in payload["markdown"]
    clean = _tool_handoff(ServerContext(str(tmp_path)),
                          {"trace": t.id, "redact": True})
    assert clean["redacted"] is True
    assert "AKIAIOSFODNN7EXAMPLE" not in clean["markdown"]
    with pytest.raises(KeyError, match="no trace"):
        _tool_handoff(ServerContext(str(tmp_path)),
                      {"trace": "ghost"})
