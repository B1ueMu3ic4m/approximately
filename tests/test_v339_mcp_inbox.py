"""v339: the inbox — the receiver's archive through MCP.

The webhook channel had a writer (posters), a keeper (the
receiver) and /stats over HTTP, but an agent inside an MCP client
could not see what had arrived. The ``inbox`` tool reads the
archive back: the stats plus the most recent rows, newest last,
redactable. The same archive is browsable as a resource — the ops
inbox, answerable without a shell.
"""

import json
import tempfile

from approximately.mcp_server import _TOOLS, ServerContext, _resources, _resources_read, _tool_inbox
from approximately.store import TraceStore

SECRET = "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"
SECRET_PAYLOAD = {"kind": "spool", "note": f"token {SECRET}"}


def _ctx_with_archive(rows):
    store = TraceStore(tempfile.mkdtemp())
    archive = store.directory / "webhook-log.jsonl"
    with archive.open("a", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
    return ServerContext(store.directory), store


def _row(verified, kind, payload):
    return {"received_at": 1.0 + len(kind), "verified": verified,
            "kind": kind, "payload": payload}


def test_tool_returns_stats_plus_recent_rows():
    ctx, _store = _ctx_with_archive([
        _row(True, "trace_failure", {"task": "a"}),
        _row(False, "spool", {"ingested": 2}),
        _row(True, "ops_digest", {"markdown": "..."}),
    ])
    payload = _tool_inbox(ctx, {})
    assert len(payload["recent"]) == 3
    assert payload["verified"] == 2 and payload["unverified"] == 1
    assert payload["kinds"] == {"trace_failure": 1, "spool": 1,
                                "ops_digest": 1}
    assert payload["recent"][-1]["kind"] == "ops_digest", \
        "newest last"


def test_limit_keeps_the_tail_not_the_head():
    ctx, _store = _ctx_with_archive([
        _row(True, f"k{i}", {"i": i}) for i in range(10)])
    payload = _tool_inbox(ctx, {"limit": 3})
    assert [r["payload"]["i"] for r in payload["recent"]] == \
        [7, 8, 9]
    assert payload["rows"] == 10


def test_redact_scrubs_rows_before_they_leave():
    ctx, _store = _ctx_with_archive([_row(True, "spool",
                                          SECRET_PAYLOAD)])
    payload = _tool_inbox(ctx, {"redact": True})
    note = payload["recent"][0]["payload"]["note"]
    assert SECRET not in note
    raw = _tool_inbox(ctx, {})["recent"][0]["payload"]["note"]
    assert SECRET in raw, "without the flag, verbatim"


def test_missing_archive_is_an_empty_inbox():
    ctx = ServerContext(TraceStore(tempfile.mkdtemp()).directory)
    payload = _tool_inbox(ctx, {})
    assert payload["recent"] == [] and payload["rows"] == 0
    assert payload["kinds"] == {}


def test_inbox_is_registered_and_browsable():
    assert "inbox" in {t["name"] for t in _TOOLS}
    ctx, store = _ctx_with_archive([_row(True, "spool", {})])
    uris = {r["uri"] for r in _resources(ctx)}
    uri = f"approximately://{store.directory}/webhook-log.jsonl"
    assert uri in uris
    reply = _resources_read({"params": {"uri": uri}}, ctx, 7)
    text = reply["result"]["contents"][0]["text"]
    row = json.loads(text.splitlines()[0])
    assert row["kind"] == "spool"


def test_fifty_tools_and_the_claim_says_so():
    from approximately import meta

    assert len(_TOOLS) == 50
    assert meta.tool_count_claim() == 50
