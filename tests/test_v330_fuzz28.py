"""Fuzz 28: poison at the receiver — and the newest surfaces.

The receiver is the first door that trusts the *network*: hostile
bodies, hostile signatures, hostile sizes. The rule under test:
refusal never crashes the server, refusal never archives, and an
archived row is a faithful record of what arrived (not of what was
true). The fleet digest and trend surfaces ride along with
degenerate stores.
"""

import json
import tempfile

from approximately.digest import build_fleet_digest
from approximately.grade import grade_trend
from approximately.mcp_server import ServerContext, _tool_digest
from approximately.receiver import ReceiverState
from approximately.store import TraceStore
from approximately.trace import Step, Trace


def _state(key=b"k"):
    return ReceiverState(Path_of_archive(), key=key)


def Path_of_archive():
    from pathlib import Path

    return Path(tempfile.mkdtemp()) / "webhook-log.jsonl"


def test_verify_rejects_every_malformed_signature():
    state = _state()
    body = b'{"kind": "x"}'
    bads = [
        None,
        "",
        "sha256=",
        "sha256=" + "0" * 64,
        "md5=deadbeef",
        "sha256=short",
        "sha256=" + "g" * 64,
        "_SHA256=AAAA",
    ]
    for sig in bads:
        verified, verdict = state.verify(body, sig)
        assert verified is False
        assert verdict == "refused", sig


def test_archive_rows_record_arrival_not_truth():
    state = _state(key=None)  # open tap
    from pathlib import Path

    state.archive = Path(tempfile.mkdtemp()) / "log.jsonl"
    body = b'{"kind": "totally-fake", "claims": "all lies"}'
    verified, _verdict = state.verify(body, None)
    assert verified is False
    # the caller archives; the row must keep what arrived verbatim
    import json as _json
    import time as _t

    row = {"received_at": _t.time(), "verified": verified,
           "kind": _json.loads(body).get("kind", "?"),
           "payload": _json.loads(body)}
    state.archive.parent.mkdir(parents=True, exist_ok=True)
    with state.archive.open("a", encoding="utf-8") as fh:
        fh.write(_json.dumps(row, sort_keys=True) + "\n")
    back = _json.loads(state.archive.read_text(
        encoding="utf-8").splitlines()[0])
    assert back["payload"] == {"kind": "totally-fake",
                               "claims": "all lies"}
    assert back["verified"] is False


def test_fleet_digest_over_degenerate_stores():
    stores = []
    for n in range(2):
        s = TraceStore(tempfile.mkdtemp())
        t = Trace(task=f"s{n}", model="m")
        t.add(Step(kind="tool_call", tool="sh", result="x",
                   tokens=0))  # zero-token degenerate
        s.save(t)
        stores.append(s)
    payload = build_fleet_digest(stores)
    assert len(payload["stores"]) == 2
    json.dumps(payload, default=str)


def test_mcp_digest_over_degenerate_store():
    s = TraceStore(tempfile.mkdtemp())
    t = Trace(task="d", model="m")
    t.add(Step(kind="tool_call", tool="sh", result="x", tokens=0))
    t.success = False
    s.save(t)
    payload = _tool_digest(ServerContext(s.directory), {})
    assert "error" not in json.dumps(payload, default=str)


def test_trend_with_one_sided_evidence_only():
    s = TraceStore(tempfile.mkdtemp())
    t = Trace(task="ancient", model="m")
    import time as _t

    t.add(Step(kind="tool_call", tool="sh", result="x", tokens=1))
    t.success = True
    t.created_at = _t.time() - 400 * 86400.0
    s.save(t)
    trend = grade_trend(s)
    assert trend["usable"] is False
    assert trend["subjects"] == []
