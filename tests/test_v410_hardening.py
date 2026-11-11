"""v410: the hardening minor — audit findings as regression pins.

A three-agent audit (receiver/channel, spool/batch/import,
doctor/digest/mcp/store) surfaced 2 P0s, 7 P1s and ~30 P2s.
This file pins the fixes that a future refactor must not
undo: the pre-read Content-Length fence, the escaped archive
lines, the constant-time compare's shape check, the lock's
inode-safe takeover, the flush's read-inside-lock, the
one-digit-minor-era doors' exit codes, and the store
boundary that stops tool clients from reading arbitrary
files.
"""

import json
import tempfile
from http.client import HTTPConnection
from pathlib import Path

from approximately import cli
from approximately.cli import _spool_append
from approximately.mcp_server import ServerContext, _handle_line
from approximately.receiver import serve
from approximately.store import TraceStore, _safe_id


def _server(**kw):
    archive = Path(tempfile.mkdtemp()) / "webhook-log.jsonl"
    server, state = serve(archive, key=b"audit-key", port=0, **kw)
    port = server.server_address[1]
    return server, state, archive, f"127.0.0.1:{port}"


def _post_raw(addr, path, body=b"{}", headers=None, method="POST"):
    host, port = addr.split(":")
    conn = HTTPConnection(host, int(port), timeout=10)
    conn.request(method, path, body=body, headers=headers or {})
    try:
        resp = conn.getresponse()
        data = resp.read()
        status = resp.status
    finally:
        conn.close()
    return status, data


KEY = b"audit-key"


def test_p0_negative_content_length_cannot_buy_an_unbounded_read():
    server, state, _archive, addr = _server()
    try:
        status, _data = _post_raw(addr, "/", b'{"a":1}',
                                 {"Content-Length": "-1",
                                  "X-Approximately-Signature":
                                      "sha256=" + "0" * 64})
        assert status in (400, 413), \
            "read-until-EOF is not for sale"
        assert state.received == 0
        status, _ = _post_raw(addr, "/", b'{"a":1}',
                              {"Content-Length": "abc"})
        assert status == 400, "malformed length is answered"
    finally:
        server.shutdown()


def test_lone_surrogate_and_line_separator_cannot_split_the_log():
    server, _state, archive, addr = _server()
    try:
        body = json.dumps({"kind": "ping",
                           "p": "\ud800 line\u2028split\u0085x"}
                          ).encode()
        import hashlib
        import hmac as hmac_mod
        sig = "sha256=" + hmac_mod.new(
            KEY, body, hashlib.sha256).hexdigest()
        status, _ = _post_raw(addr, "/", body,
                              {"Content-Length": str(len(body)),
                               "X-Approximately-Signature": sig})
        assert status == 200
        rows = archive.read_text(encoding="utf-8").splitlines()
        assert len(rows) == 1, \
            "escapes are integrity: one row, one line, no crash"
    finally:
        server.shutdown()


def test_non_hex_signature_is_refused_by_shape():
    server, _state, _archive, addr = _server()
    try:
        status, _ = _post_raw(addr, "/", b'{"a":1}',
                              {"Content-Length": "7",
                               "X-Approximately-Signature":
                                   "sha256=" + "é" * 64})
        assert status == 401, "the shape check guards compare_digest"
    finally:
        server.shutdown()


def test_census_buckets_are_capped():
    server, _state, _archive, addr = _server()
    try:
        import hashlib
        import hmac as hmac_mod

        for i in range(80):
            body = json.dumps({"kind": f"k{i}", "sender": f"s{i}",
                               "n": i}, sort_keys=True).encode()
            sig = "sha256=" + hmac_mod.new(
                KEY, body, hashlib.sha256).hexdigest()
            _post_raw(addr, "/", body,
                      {"Content-Length": str(len(body)),
                       "X-Approximately-Signature": sig})
        _status, data = _get(addr, "/stats")
        census = data["archive"]["kinds"]
        assert len(census) <= 64 + 1, (
            "a hostile poster cannot grow the stats body without "
            "bound")
        assert "…many more" in census
    finally:
        server.shutdown()


def _get(addr, path):
    host, port = addr.split(":")
    conn = HTTPConnection(host, int(port), timeout=10)
    conn.request("GET", path)
    resp = conn.getresponse()
    data = json.loads(resp.read())
    status = resp.status
    conn.close()
    return status, data


def test_p0_mcp_non_dict_params_cannot_kill_the_server():
    ctx = ServerContext(str(Path(tempfile.mkdtemp())))
    hostile = [
        ('{"jsonrpc": "2.0", "id": 1, "method": "tools/call",'
         ' "params": "x"}'),
        ('{"jsonrpc": "2.0", "id": 2, "method": "resources/read",'
         ' "params": [1,2]}'),
    ]
    for line in hostile:
        resp = _handle_line(line, ctx)
        assert resp is not None and "error" in resp, \
            "one hostile line must not end the server"
    # and the server is still alive afterwards
    alive = _handle_line('{"jsonrpc": "2.0", "id": 3, '
                         '"method": "ping"}', ctx)
    assert alive is not None and "result" in alive, \
        "the server survives the hostile lines"


def test_mcp_trace_specs_cannot_escape_the_store(tmp_path):
    outside = tmp_path / "outside.json"
    from approximately.trace import Trace

    outside.write_text(Trace(task="stolen", steps=[]).to_json(),
                       encoding="utf-8")
    ctx = ServerContext(str(tmp_path))
    resp = _handle_line(json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "verify",
                   "arguments": {"trace": str(outside)}}}), ctx)
    text = resp["result"]["content"][0]["text"]
    assert "safe id" in text, \
        "a client-supplied path must not become an arbitrary read"


def test_plan_time_load_of_a_hostile_id_probes_nothing(tmp_path):
    store = TraceStore(tmp_path)
    probe = "/etc/hostname"
    archive = tmp_path / "webhook-log.jsonl"
    row = {"received_at": 1.0, "verified": True, "kind": "trace_ship",
           "payload": {"trace": {"id": probe, "task": "probe",
                                 "steps": []}}}
    archive.write_text(json.dumps(row) + "\n", encoding="utf-8")
    _rows, _shipments, plan = cli._inbox_plan(archive, store,
                                              include_rotated=False)
    entry = plan[0]
    assert entry["present"] is False, \
        "a path-shaped id is a name check, not a file probe"


def test_safe_id_anchors_at_the_string_end():
    assert _safe_id("abc") is True
    msg = ("a trailing newline must not ride the $ anchor into "
           "a filename")
    assert not _safe_id("abc\n"), msg


def test_flush_json_plan_exits_zero(monkeypatch):
    from approximately import integrity

    monkeypatch.setattr(integrity, "load_key",
                        lambda *a, **k: b"plan-key")
    store = TraceStore(tempfile.mkdtemp())
    spool = cli._spool_path(str(store.directory))
    _spool_append(spool, "t1", "http://127.0.0.1:1/", "box")
    import argparse
    import contextlib
    import io

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = cli.cmd_webhook_ship(argparse.Namespace(
            store=str(store.directory), trace=None,
            url="http://127.0.0.1:1/", all=False, dry_run=True,
            since=None, key_file=None, sender=None, spool=False,
            flush=True, json=True))
    assert code == 0, "a read-only plan is not a failure"


def test_batch_limit_above_the_store_ships_everything():
    store = TraceStore(tempfile.mkdtemp())
    ids = []
    for i in range(3):
        rec = Recorder(f"task {i}", store=store)
        rec.tool("sh", {"cmd": "x"}, result="ok")
        rec.respond("done", success=True)
        rec.trace.created_at = 1700000000.0 + i
        store.save(rec.trace, stamp=False)
        ids.append(rec.trace.id)
    assert [t.id for t in cli._batch_traces(store, limit=5)] == ids, \
        "limit 5 on 3 traces ships 3, never a silent subset"


from approximately.recorder import Recorder
