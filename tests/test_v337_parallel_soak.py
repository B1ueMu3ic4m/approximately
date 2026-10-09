"""v337: the receiver under concurrency — no lost hits, no torn
lines.

ThreadingHTTPServer serves posts on parallel threads, so the
bookkeeping (``received``/``refused`` counters, the JSONL append)
races unless it serializes. This soak fires 200 signed posts from
20 threads at one receiver and demands exact bookkeeping: every
post accepted, every counter right, every archive line intact — a
torn or interleaved line is a lie in the ops record.
"""

import hashlib
import hmac
import json
import tempfile
import threading
from http.client import HTTPConnection
from pathlib import Path

from approximately.receiver import serve

KEY = b"concurrent-sekrit"
THREADS = 20
PER_THREAD = 10


def _signed(body: bytes) -> str:
    return "sha256=" + hmac.new(KEY, body, hashlib.sha256).hexdigest()


def _post(addr, body: bytes):
    host, port = addr.split(":")
    conn = HTTPConnection(host, int(port), timeout=10)
    conn.request("POST", "/", body=body, headers={
        "Content-Type": "application/json",
        "X-Approximately-Signature": _signed(body)})
    resp = conn.getresponse()
    status = resp.status
    resp.read()
    conn.close()
    return status


def test_two_hundred_concurrent_posts_bookkeep_exactly():
    archive = Path(tempfile.mkdtemp()) / "webhook-log.jsonl"
    server, state = serve(archive, port=0, key=KEY)
    addr = f"127.0.0.1:{server.server_address[1]}"
    statuses: list = []
    statuses_lock = threading.Lock()

    def worker(n: int) -> None:
        mine = []
        for i in range(PER_THREAD):
            body = json.dumps({"kind": "trace_failure",
                               "task": f"t{n}-{i}"}).encode()
            mine.append(_post(addr, body))
        with statuses_lock:
            statuses.extend(mine)

    threads = [threading.Thread(target=worker, args=(n,))
               for n in range(THREADS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    try:
        assert statuses == [200] * (THREADS * PER_THREAD), \
            f"accepted {statuses.count(200)} of {len(statuses)}"
        assert state.received == THREADS * PER_THREAD, \
            "a lost increment is a lie in the ops record"
        raw = archive.read_bytes().decode("utf-8")
        lines = raw.splitlines()
        assert len(lines) == THREADS * PER_THREAD, \
            "every accepted post lines up exactly once"
        tasks = set()
        for line in lines:
            row = json.loads(line)  # a torn line raises here
            tasks.add(row["payload"]["task"])
        assert len(tasks) == THREADS * PER_THREAD, \
            "no post landed twice or vanished"
    finally:
        server.shutdown()


def test_refusal_counters_serialize_under_mixed_fire():
    archive = Path(tempfile.mkdtemp()) / "webhook-log.jsonl"
    server, state = serve(archive, port=0, key=KEY)
    addr = f"127.0.0.1:{server.server_address[1]}"

    def hostile(n: int) -> None:
        for _ in range(PER_THREAD):
            host, port = addr.split(":")
            conn = HTTPConnection(host, int(port), timeout=10)
            conn.request("POST", "/", body=b'{"kind": "forge"}',
                         headers={"Content-Type": "application/json",
                                  "X-Approximately-Signature":
                                  "sha256=" + "0" * 64})
            conn.getresponse().read()
            conn.close()

    threads = [threading.Thread(target=hostile, args=(n,))
               for n in range(THREADS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    try:
        assert state.refused == THREADS * PER_THREAD, \
            "every forgery counted, none lost"
        assert state.received == 0 and not archive.exists(), \
            "refusal never archives"
    finally:
        server.shutdown()
