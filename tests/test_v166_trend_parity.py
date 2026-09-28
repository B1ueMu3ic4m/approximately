"""v166: slowness trend parity — CLI table, MCP payload, status prose.

`fleet --trend` prints a slowness line when two days of history
exist; the MCP `trend` payload carries `anomaly_trend`; and the
status frame's prose mentions it. One summarize_trend, three
surfaces.
"""

import argparse
import json
import time

from approximately.cli import cmd_status
from approximately.fleet import (
    append_digest,
    digest_snapshot,
    render_trend,
    summarize_trend,
    survey,
    trend_days,
)
from approximately.mcp_server import ServerContext, handle_request
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _seed_with_digest(tmp_path, days=2):
    store = TraceStore(tmp_path / "s")
    jitter = (1800, 2000, 2100, 1900)
    for i in range(4):
        rec = Recorder(f"boring {i}", save=False)
        rec.tool("search", {"q": str(i)}, result="hit")
        rec.respond("done", success=True)
        rec.trace.steps[0].latency_ms = jitter[i]
        store.save(rec.trace)
    slow = Recorder("the slow one", save=False)
    slow.tool("search", {"q": "heavy"}, result="hit")
    slow.respond("done", success=True)
    slow.trace.steps[0].latency_ms = 30000
    store.save(slow.trace)
    digest_dir = tmp_path / "d"
    summaries = survey([store.directory])
    for offset in reversed(range(1, days + 1)):
        snap = digest_snapshot(summaries)
        snap["ts"] = time.time() - offset * 86400
        append_digest(digest_dir, snap)
    return store, digest_dir


def test_render_trend_prints_slowness(tmp_path, capsys):
    _store, digest_dir = _seed_with_digest(tmp_path)
    summary = summarize_trend(trend_days(digest_dir))
    text = render_trend(summary)
    assert "slowness trend:" in text
    assert "flagged step(s)" in text


def test_mcp_trend_carries_anomaly_trend(tmp_path):
    store, digest_dir = _seed_with_digest(tmp_path)
    ctx = ServerContext(str(store.directory))
    payload = handle_request({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "trend",
                   "arguments": {"digest_dir": str(digest_dir)}},
    }, ctx)
    result = json.loads(payload["result"]["content"][0]["text"])
    assert result["anomaly_trend"]["latest"] == 1


def test_status_prose_includes_slowness(tmp_path, capsys):
    store, digest_dir = _seed_with_digest(tmp_path)
    args = argparse.Namespace(store=str(store.directory), since=None,
                              digest_dir=str(digest_dir), json=False,
                              watch=False, interval=30.0, frames=None)
    assert cmd_status(args) == 0
    assert "slowness trend:" in capsys.readouterr().out
