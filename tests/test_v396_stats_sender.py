"""v396: curl can ask "what did box-a ship?" too.

The /stats query vocabulary was kind, contains, since — sender
was the one filter the one-reader served that curl could not
name, so a receiver serving several boxes needed the CLI door
or the MCP tool just to scope by shipper. sender joins the
vocabulary now, with the same strict refusals: an unknown
parameter, a repeated parameter (an ambiguous request) or a
hostile value is a 400 naming the reason — a typo'd check can
never silently look like the truth.
"""

import json
import tempfile
from http.client import HTTPConnection
from pathlib import Path

from approximately.receiver import parse_stats_query, serve


def _rows_archive():
    archive = Path(tempfile.mkdtemp()) / "webhook-log.jsonl"
    rows = []
    for i, (sender, kind) in enumerate(
            [("box-a", "trace_ship"), ("box-a", "trace_ship"),
             ("box-b", "ping")]):
        rows.append({"received_at": 1.0 + i, "verified": True,
                     "kind": kind,
                     "payload": {"trace": {"id": f"t{i}",
                                           "task": "x",
                                           "steps": []},
                                 "sender": sender}})
    with archive.open("a", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, sort_keys=True) + "\n")
    return archive


def _server():
    server, _state = serve(_rows_archive(), port=0)
    port = server.server_address[1]
    return server, f"127.0.0.1:{port}"


def _get(addr, path):
    host, port = addr.split(":")
    conn = HTTPConnection(host, int(port), timeout=5)
    conn.request("GET", path)
    resp = conn.getresponse()
    data = json.loads(resp.read())
    status = resp.status
    conn.close()
    return status, data


def test_the_vocabulary_gains_sender():
    filters = parse_stats_query("sender=box-a")
    assert filters == {"sender": "box-a"}


def test_the_strict_refusals_cover_sender():
    import pytest

    with pytest.raises(ValueError, match="repeated"):
        parse_stats_query("sender=a&sender=b")
    with pytest.raises(ValueError, match="unknown"):
        parse_stats_query("shipped=box-a")


def test_the_endpoint_scopes_by_sender():
    server, addr = _server()
    try:
        status, data = _get(addr, "/stats?sender=box-a")
        assert status == 200
        assert data["archive"]["rows"] == 2
        assert data["archive"]["senders"] == {"box-a": 2}, \
            "the scoped census describes the matches"
        assert data["archive"]["kinds"] == {"trace_ship": 2}
        status, data = _get(addr, "/stats?sender=box-b")
        assert data["archive"]["rows"] == 1
        assert data["archive"]["senders"] == {"box-b": 1}
    finally:
        server.shutdown()


def test_an_unknown_parameter_is_still_a_400():
    server, addr = _server()
    try:
        status, data = _get(addr, "/stats?shipped=box-a")
        assert status == 400
        assert "unknown" in data["error"]
    finally:
        server.shutdown()
