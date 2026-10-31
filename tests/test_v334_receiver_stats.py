"""v334: /stats — the archive read back, not remembered.

``/health`` counts what this process has seen since it started; a
restarted server forgets. ``/stats`` reads the JSONL on disk and
reports the log's actual contents — rows, the verified split, the
kind census, the last arrival, the byte size — so an on-call can
answer "what does this log hold" without shelling into the box.
Malformed lines are counted, never guessed at.
"""

import json
import tempfile
from http.client import HTTPConnection
from pathlib import Path

from approximately.receiver import archive_stats, serve


def _get(addr, path):
    host, port = addr.split(":")
    conn = HTTPConnection(host, int(port), timeout=5)
    conn.request("GET", path)
    resp = conn.getresponse()
    data = json.loads(resp.read())
    status = resp.status
    conn.close()
    return status, data


def _server():
    archive = Path(tempfile.mkdtemp()) / "webhook-log.jsonl"
    server, _state = serve(archive, port=0)
    port = server.server_address[1]
    return server, archive, f"127.0.0.1:{port}"


def test_stats_on_an_empty_archive():
    server, _archive, addr = _server()
    try:
        status, data = _get(addr, "/stats")
        assert status == 200
        assert data["archive"] == {"rows": 0, "verified": 0,
                                   "unverified": 0, "malformed": 0,
                                   "kinds": {}, "bytes": 0,
                                   "last_received_at": None,
                                   "first_malformed": None}
        assert data["received"] == 0 and data["refused"] == 0
    finally:
        server.shutdown()


def test_stats_reflect_what_arrived():
    server, archive, addr = _server()
    try:
        for body in (b'{"kind": "trace_failure", "task": "a"}',
                     b'{"kind": "digest", "window": "night"}',
                     b'{"kind": "trace_failure", "task": "b"}'):
            conn = HTTPConnection(addr.split(":")[0],
                                  int(addr.split(":")[1]), timeout=5)
            conn.request("POST", "/", body=body,
                         headers={"Content-Type": "application/json"})
            resp = conn.getresponse()
            assert resp.status == 200
            resp.read()
            conn.close()
        status, data = _get(addr, "/stats")
        assert status == 200
        arc = data["archive"]
        assert arc["rows"] == 3
        assert arc["verified"] == 0 and arc["unverified"] == 3, \
            "open tap marks every row unverified"
        assert arc["kinds"] == {"trace_failure": 2, "digest": 1}
        assert arc["bytes"] == archive.stat().st_size
        assert arc["last_received_at"] is not None
    finally:
        server.shutdown()


def test_malformed_line_is_counted_never_crashing():
    server, archive, addr = _server()
    try:
        with archive.open("a", encoding="utf-8") as fh:
            fh.write('{"kind": "real", "verified": true}\n')
            fh.write("not json at all\n")
            fh.write('["a list, not an object"]\n')
        status, data = _get(addr, "/stats")
        assert status == 200
        arc = data["archive"]
        assert arc["rows"] == 1 and arc["verified"] == 1
        assert arc["malformed"] == 2, "poison is counted, not parsed"
    finally:
        server.shutdown()


def test_health_contract_unchanged_and_404_holds():
    server, _archive, addr = _server()
    try:
        status, data = _get(addr, "/health")
        assert status == 200
        assert set(data) == {"ok", "received", "refused",
                             "verify_mode"}
        status, data = _get(addr, "/nope")
        assert status == 404 and "error" in data
    finally:
        server.shutdown()


def test_archive_stats_on_a_missing_file():
    stats = archive_stats(Path(tempfile.mkdtemp()) / "absent.jsonl")
    assert stats["rows"] == 0 and stats["bytes"] == 0


def test_first_malformed_is_named_truncated():
    archive = Path(tempfile.mkdtemp()) / "webhook-log.jsonl"
    poison = "not json garbage here"
    archive.write_text(
        json.dumps({"kind": "ok", "verified": True}) + "\n"
        + poison + "\n"
        + "[" * 200 + "\n", encoding="utf-8")
    stats = archive_stats(archive)
    assert stats["malformed"] == 2
    assert stats["first_malformed"] == poison, \
        "the first poison is recognisable"
    assert len(stats["first_malformed"]) == len(poison)


def test_first_malformed_is_truncated_to_eighty():
    archive = Path(tempfile.mkdtemp()) / "webhook-log.jsonl"
    archive.write_text("x" * 500 + "\n", encoding="utf-8")
    stats = archive_stats(archive)
    assert len(stats["first_malformed"]) == 80, \
        "enough to recognise, never enough to be it"


def test_clean_archive_has_no_first_malformed():
    archive = Path(tempfile.mkdtemp()) / "webhook-log.jsonl"
    archive.write_text(json.dumps({"kind": "ok",
                                   "verified": True}) + "\n",
                       encoding="utf-8")
    assert archive_stats(archive)["first_malformed"] is None
