"""v378: the reader's last hole closes.

The parity sweep missed one: the CLI's `received` door folds the
rotated log in with `--include-rotated`, but the MCP inbox tool
had no twin — a caller asking the tool "what landed yesterday"
got only today's log and no way to know it was looking at half
the story. The tool carries `include_rotated` now, and
SECURITY.md names the probe's refusal posture: a typo'd check
gets a 400 naming the reason, never a silent lie.
"""

import json
import tempfile
from pathlib import Path

from approximately.mcp_server import ServerContext, _tool_inbox
from approximately.store import TraceStore

_ROOT = Path(__file__).resolve().parents[1]


def _store_with_rotation():
    store = TraceStore(tempfile.mkdtemp())
    archive = store.directory / "webhook-log.jsonl"
    rotated = store.directory / "webhook-log.jsonl.1"
    rows = [{"received_at": 1.0, "verified": True, "kind": "old",
             "payload": {}}]
    with rotated.open("a", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
    fresh = [{"received_at": 2.0, "verified": True,
              "kind": "new", "payload": {}}]
    with archive.open("a", encoding="utf-8") as fh:
        for row in fresh:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
    return store


def test_mcp_inbox_include_rotated_folds_yesterday_in():
    store = _store_with_rotation()
    ctx = ServerContext(store.directory)
    today = _tool_inbox(ctx, {})
    assert [r["kind"] for r in today["recent"]] == ["new"]
    both = _tool_inbox(ctx, {"include_rotated": True})
    assert [r["kind"] for r in both["recent"]] == ["old", "new"], \
        "yesterday's log rides ahead of the current one"


def test_the_census_stays_the_current_logs_stats_shape():
    # the reader's contract: rows/verified/kinds are the /stats
    # shape of the current log; include_rotated widens the VIEW
    # (recent), never rewrites the census
    store = _store_with_rotation()
    ctx = ServerContext(store.directory)
    today = _tool_inbox(ctx, {})
    assert today["kinds"] == {"new": 1}
    both = _tool_inbox(ctx, {"include_rotated": True})
    assert both["kinds"] == {"new": 1} and both["rows"] == 1, \
        "the census is the current log's, same shape /stats answers"


def test_security_md_names_the_probe_refusal_posture():
    text = (_ROOT / "docs" / "SECURITY.md").read_text(
        encoding="utf-8")
    assert "unknown query parameter" in text and "400" in text, \
        "the probe's refusal posture is on the security page"
