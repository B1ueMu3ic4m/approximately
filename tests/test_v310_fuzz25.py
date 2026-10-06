"""v310: fuzz 25 — cross-door chains under poison.

Single-door fuzz rounds found single-door lies. This round poisons
the CHAINS: redact feeds handoff feeds evidence; the price catalog
feeds budget; triage feeds annotate; tail feeds the snapshot. The
chain contract: each door's output is the next door's untrusted
input, and no poisoning of an upstream store may crash or silently
lie downstream.
"""

import json

from approximately.evidence import build_evidence_pack
from approximately.handoff import brief
from approximately.mcp_server import ServerContext, _tool_triage
from approximately.prices import set_rate
from approximately.redact import compile_patterns, redact_trace
from approximately.snapshot import restore, snapshot
from approximately.store import TraceStore
from approximately.trace import Step, Trace
from approximately.triage import triage_store


def _poisoned_store(tmp_path):
    """A store with hostile-but-parseable records."""
    store = TraceStore(tmp_path)
    t = Trace(task="deploy \x00 rotate sk-abcdefghijklmnopqrst",
              model="m")
    t.add(Step(kind="tool_call", tool="sh", result="ok",
               tokens=10**9, latency_ms=10**7))
    t.add(Step(kind="error", error="AKIAIOSFODNN7EXAMPLE denied"))
    t.success = False
    t.meta = {"budget": {"exceeded": True}, "x": ["nested", {"deep": 1}]}
    store.save(t)
    return store, t


def test_redact_to_handoff_to_evidence_chain(tmp_path):
    store, t = _poisoned_store(tmp_path)
    share, rep = redact_trace(t, compile_patterns())
    assert rep["total"] >= 2
    # the share copy feeds handoff: the brief scrubs again (nothing
    # left to find) and never crashes on the null byte task
    page = brief(share, store, table=compile_patterns())
    assert "sk-abcdefghijklmnopqrst" not in page
    assert "AKIAIOSFODNN7EXAMPLE" not in page
    # handoff of the POISONED original with redaction also holds
    page2 = brief(t, store, table=compile_patterns())
    assert "AKIAIOSFODNN7EXAMPLE" not in page2
    # evidence pack of the share copy carries the grade + brief
    store.save(share)
    out = tmp_path / "case.zip"
    m = build_evidence_pack(store, share.id, out)
    assert m["agent_grade"] is None  # share has no agent steps
    assert "brief.md" in m["members"]


def test_prices_to_budget_chain_extremes(tmp_path):
    store = TraceStore(tmp_path)
    t = Trace(task="burn", model="m")
    t.add(Step(kind="tool_call", tool="sh", result="x", tokens=10**9))
    t.success = True
    store.save(t)
    set_rate(tmp_path, "m", 1e300)  # absurd but finite
    import argparse
    import contextlib
    import io

    from approximately.cli import cmd_budget

    args = argparse.Namespace(store=str(tmp_path), trace=t.id,
                              tokens=None, usd=1.0, prices=None,
                              on_exceed="stamp", agent=None,
                              **{"json": True})
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        assert cmd_budget(args) == 0
    payload = json.loads(buf.getvalue())
    assert payload["would_trip"] is True  # the absurd price still


def test_triage_to_annotate_chain_with_meta_shapes(tmp_path):
    store = TraceStore(tmp_path)
    t = Trace(task="meta shapes", model="m")
    t.add(Step(kind="tool_call", tool="sh", result="x"))
    t.success = False
    t.meta = {"budget": "exceeded", "budgetx": {"exceeded": True}}
    store.save(t)
    rows = triage_store(store)
    assert len(rows) == 1  # not a stamped breach (string meta)
    payload = _tool_triage(ServerContext(str(tmp_path)), {})
    assert payload["total"] == 1


def test_tail_to_snapshot_chain(tmp_path):
    from approximately.tail import tail

    store = TraceStore(tmp_path)
    t = Trace(task="snap me", model="m")
    t.add(Step(kind="tool_call", tool="sh", result="x"))
    t.success = False
    store.save(t)
    lines = tail(store, once=True)
    # once is the stateless snapshot: existing seeds the seen-set
    assert lines and "already on file" in lines[0]
    # arrivals during a watch still flag; --max-passes bounds it
    t2 = Trace(task="arrive then snap", model="m")
    t2.add(Step(kind="tool_call", tool="sh", result="x"))
    t2.success = False
    import threading

    threading.Timer(0.15, store.save, args=(t2,)).start()
    lines2 = tail(store, once=False, interval=0.1, max_passes=8)
    assert any(">> ALERT" in line for line in lines2)
    out = tmp_path / "s.zip"
    rep = snapshot(tmp_path, out)
    r = restore(out, tmp_path / "r")
    assert r["members"] == rep["members"] >= 2
