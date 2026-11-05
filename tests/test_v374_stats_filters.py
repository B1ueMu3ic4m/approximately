"""v374: the /stats probe answers the same filters.

After v372 and v373, every surface but one answered the reader's
filters. The curl probe still returned only the channel-global
census: ``/stats?kind=spool`` was 404 territory, and an unknown
query parameter would have been silently ignored — a typo'd
check that always looks like the truth. /stats now scopes
rows/verified/unverified/kinds to the filter (bytes, malformed
and first_malformed stay channel-global: they describe the log,
not the filter), and refuses unknown parameters and hostile
values with a 400 — the probe lies about nothing.
"""

import json
import tempfile
import time
from http.client import HTTPConnection
from pathlib import Path

from approximately.receiver import serve


def _server():
    archive = Path(tempfile.mkdtemp()) / "webhook-log.jsonl"
    server, _state = serve(archive, port=0)
    port = server.server_address[1]
    return server, archive, f"127.0.0.1:{port}"


def _get(addr, path):
    host, port = addr.split(":")
    conn = HTTPConnection(host, int(port), timeout=5)
    conn.request("GET", path)
    resp = conn.getresponse()
    data = json.loads(resp.read())
    status = resp.status
    conn.close()
    return status, data


def _seed(archive, rows):
    with archive.open("a", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, sort_keys=True) + "\n")


def _rows(now):
    return [{"received_at": now - 50, "verified": True,
             "kind": "trace_failure", "payload": {"cmd": "deploy"}},
            {"received_at": now - 100, "verified": False,
             "kind": "spool", "payload": {"cmd": "cleanup"}},
            {"received_at": now - 9000, "verified": True,
             "kind": "spool", "payload": {"cmd": "test"}}]


def test_kind_scopes_the_census():
    server, archive, addr = _server()
    try:
        now = time.time()
        _seed(archive, _rows(now))
        status, data = _get(addr, "/stats?kind=spool")
        assert status == 200
        scoped = data["archive"]
        assert scoped["rows"] == 2
        assert scoped["verified"] == 1
        assert scoped["unverified"] == 1
        assert scoped["kinds"] == {"spool": 2}, \
            "the filter's own kind is the whole census"
        assert scoped["bytes"] > 0, \
            "the log's size stays channel-global"
    finally:
        server.shutdown()


def test_contains_and_since_scope_the_census():
    server, archive, addr = _server()
    try:
        now = time.time()
        _seed(archive, _rows(now))
        status, data = _get(addr, "/stats?contains=deploy")
        assert status == 200
        assert data["archive"]["rows"] == 1
        assert data["archive"]["kinds"] == {"trace_failure": 1}
        status, data = _get(addr, f"/stats?since={now - 120}")
        assert status == 200
        assert data["archive"]["rows"] == 2, \
            "the 9000-second-old row falls out"
    finally:
        server.shutdown()


def test_unknown_parameter_is_a_400_not_a_lie():
    server, _archive, addr = _server()
    try:
        status, data = _get(addr, "/stats?kinds=spool")
        assert status == 400
        assert "unknown query parameter" in data["error"]
        assert "kinds" in data["error"], "the typo is named"
    finally:
        server.shutdown()


def test_hostile_since_is_a_400():
    server, _archive, addr = _server()
    try:
        status, data = _get(addr, "/stats?since=30m")
        assert status == 400
        assert "unix timestamp" in data["error"]
    finally:
        server.shutdown()


def test_filtered_stats_function_scopes_like_the_probe():
    from approximately.receiver import filtered_stats

    archive = Path(tempfile.mkdtemp()) / "webhook-log.jsonl"
    now = time.time()
    _seed(archive, _rows(now))
    scoped = filtered_stats(archive, kind="spool")
    assert scoped["rows"] == 2
    assert scoped["kinds"] == {"spool": 2}
    assert scoped["malformed"] == 0
    assert scoped["last_received_at"] is not None, \
        "channel-global fields survive the scoping"
    empty = filtered_stats(archive, contains="nonexistent")
    assert empty["rows"] == 0 and empty["kinds"] == {}
