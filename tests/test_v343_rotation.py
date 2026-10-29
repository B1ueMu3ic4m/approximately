"""v343: the archive rotates — an unbounded JSONL is a slow
disk-fill, not a record.

``--max-rows`` (default 100k) rotates the archive when it fills:
the previous log moves aside as ``<log>.1`` (os.replace — atomic
even on Windows), the archive starts empty, the counters keep
telling the truth. 0 means unbounded, and says so.
"""

import json
import tempfile
import time
from http.client import HTTPConnection
from pathlib import Path

from approximately.receiver import serve


def _post(addr, body):
    host, port = addr.split(":")
    conn = HTTPConnection(host, int(port), timeout=5)
    conn.request("POST", "/", body=body,
                 headers={"Content-Type": "application/json"})
    resp = conn.getresponse()
    data = json.loads(resp.read())
    conn.close()
    return resp.status, data


def _fire(addr, n):
    for i in range(n):
        status, _ = _post(addr, json.dumps(
            {"kind": "k", "seq": i}).encode())
        assert status == 200


def test_rotation_moves_aside_and_starts_empty():
    archive = Path(tempfile.mkdtemp()) / "log.jsonl"
    server, state = serve(archive, port=0, max_rows=3)
    addr = f"127.0.0.1:{server.server_address[1]}"
    try:
        _fire(addr, 8)
        time.sleep(0.1)
        assert len(archive.read_text().splitlines()) == 2, \
            "the archive holds the rows since the last rotation"
        rotated = Path(str(archive) + ".1")
        assert len(rotated.read_text().splitlines()) == 3, \
            "the previous log moved aside whole"
        assert state.received == 8, "the counters never lose a hit"
    finally:
        server.shutdown()


def test_rotation_survives_a_restart_on_the_same_file():
    archive = Path(tempfile.mkdtemp()) / "log.jsonl"
    archive.write_text(  # history from a previous life
        "\n".join(json.dumps({"received_at": 0, "verified": False,
                              "kind": "old", "payload": {}})
                  for _ in range(3)) + "\n", encoding="utf-8")
    server, _state = serve(archive, port=0, max_rows=5)
    addr = f"127.0.0.1:{server.server_address[1]}"
    try:
        _fire(addr, 4)
        time.sleep(0.1)
        rotated = Path(str(archive) + ".1")
        assert rotated.is_file(), \
            "the pre-existing rows count toward the bound"
        assert len(rotated.read_text().splitlines()) == 5
        assert len(archive.read_text().splitlines()) == 2
    finally:
        server.shutdown()


def test_zero_means_unbounded_and_says_so():
    from approximately.receiver import ReceiverState

    state = ReceiverState(Path(tempfile.mkdtemp()) / "l.jsonl",
                          max_rows=0)
    assert state.max_rows == 0


def test_health_and_stats_stay_truthful_across_rotation():
    archive = Path(tempfile.mkdtemp()) / "log.jsonl"
    server, _state = serve(archive, port=0, max_rows=2)
    addr = f"127.0.0.1:{server.server_address[1]}"
    try:
        _fire(addr, 5)
        time.sleep(0.1)
        host, port = addr.split(":")
        conn = HTTPConnection(host, int(port), timeout=5)
        conn.request("GET", "/stats")
        stats = json.loads(conn.getresponse().read())
        conn.close()
        assert stats["received"] == 5
        assert stats["archive"]["rows"] == 1, \
            "the archive section reads the disk, not the counters"
    finally:
        server.shutdown()
