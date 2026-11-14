"""v420: the replay dies at the window — and the retry lives.

A captured request was forever: the MAC covered the body alone,
so any sniffed post re-verified whenever it was replayed. Now
the sender stamps its posts (``X-Approximately-Timestamp``), the
MAC covers ``stamp + newline + body``, a timestamp outside the
replay window is refused, and a signature claimed once inside
the window is idempotent delivery — ``200 duplicate``, no
second row — because the honest sender's retry after a lost
response must land, and the replay injects nothing. Legacy
body-only posts still verify (receivers meet old senders in
the wild) and can be refused outright with
``--require-timestamp``. The claim happens at acceptance, not
at verification: a post refused by the rate gate must claim
nothing, so its retry lands fresh.
"""

import hashlib
import hmac as hmac_mod
import json
import tempfile
import time
from http.client import HTTPConnection
from pathlib import Path

from approximately.fleet import notify_webhook
from approximately.receiver import REPLAY_CACHE_MAX, serve

KEY = b"replay-key"


def _server(**kw):
    archive = Path(tempfile.mkdtemp()) / "webhook-log.jsonl"
    server, state = serve(archive, key=KEY, port=0, **kw)
    addr = f"127.0.0.1:{server.server_address[1]}"
    return server, state, archive, addr


def _post(addr, body, stamp=None, key=KEY, sig_over=None):
    """One raw post: the MAC covers ``stamp + newline + body``
    when a stamp is given, the body alone when it is not."""
    sig_material = sig_over if sig_over is not None else \
        (stamp.encode() + b"\n" + body if stamp is not None
         else body)
    sig = "sha256=" + hmac_mod.new(key, sig_material,
                                   hashlib.sha256).hexdigest()
    host, port = addr.split(":")
    conn = HTTPConnection(host, int(port), timeout=10)
    headers = {"Content-Length": str(len(body)),
               "X-Approximately-Signature": sig}
    if stamp is not None:
        headers["X-Approximately-Timestamp"] = stamp
    conn.request("POST", "/", body=body, headers=headers)
    resp = conn.getresponse()
    data = json.loads(resp.read())
    status = resp.status
    conn.close()
    return status, data


PING = b'{"kind": "ping", "n": 1}'


def test_a_stamped_post_verifies_and_archives_its_scheme():
    server, state, archive, addr = _server()
    try:
        stamp = str(int(time.time()))
        status, data = _post(addr, PING, stamp)
        assert status == 200 and data["received"] is True
        assert state.received == 1
        rows = json.loads(archive.read_text().splitlines()[0])
        assert rows["scheme"] == "timestamped"
        assert rows["verified"] is True
    finally:
        server.shutdown()


def test_a_captured_request_is_an_echo_not_a_second_row():
    server, state, archive, addr = _server()
    try:
        stamp = str(int(time.time()))
        status, _ = _post(addr, PING, stamp)
        assert status == 200
        # the exact same bytes, replayed by whoever captured them
        status, data = _post(addr, PING, stamp)
        assert status == 200, \
            "the echo answers success (the retry must land)"
        assert data.get("duplicate") is True, \
            "and names itself as a duplicate"
        assert state.received == 1, "no second row"
        assert state.duplicates == 1
        assert len(archive.read_text().splitlines()) == 1
    finally:
        server.shutdown()


def test_a_captured_request_dies_at_the_windows_edge():
    server, state, _archive, addr = _server(replay_window=60.0)
    try:
        old_stamp = str(int(time.time()) - 300)
        sig = "sha256=" + hmac_mod.new(
            KEY, old_stamp.encode() + b"\n" + PING,
            hashlib.sha256).hexdigest()
        host, port = addr.split(":")
        conn = HTTPConnection(host, int(port), timeout=10)
        conn.request("POST", "/", body=PING,
                     headers={"Content-Length": str(len(PING)),
                              "X-Approximately-Signature": sig,
                              "X-Approximately-Timestamp":
                                  old_stamp})
        resp = conn.getresponse()
        assert resp.status == 401, \
            "outside the window the MAC proves nothing"
        assert "replay window" in json.loads(resp.read())["error"]
        conn.close()
        assert state.received == 0
    finally:
        server.shutdown()


def test_a_slightly_skewed_clock_still_verifies():
    server, _state, _archive, addr = _server(replay_window=60.0)
    try:
        stamp = str(int(time.time()) - 30)
        status, _ = _post(addr, PING, stamp)
        assert status == 200, \
            "a 30-second skew is inside a 60-second window"
    finally:
        server.shutdown()


def test_a_malformed_timestamp_is_answered_not_guessed():
    server, state, _archive, addr = _server()
    try:
        stamp = "abc"
        status, data = _post(addr, PING, stamp)
        assert status == 400 and "malformed" in data["error"]
        assert state.received == 0, \
            "a malformed stamp is refused before any MAC work"
    finally:
        server.shutdown()


def test_legacy_posts_still_verify_by_default():
    server, _state, archive, addr = _server()
    try:
        status, _ = _post(addr, PING)  # no stamp, body-only MAC
        assert status == 200
        row = json.loads(archive.read_text().splitlines()[0])
        assert row["scheme"] == "legacy"
    finally:
        server.shutdown()


def test_require_timestamp_refuses_the_legacy_scheme():
    server, _state, _archive, addr = _server(allow_legacy=False)
    try:
        status, data = _post(addr, PING)
        assert status == 401 and "timestamp" in data["error"], \
            "--require-timestamp is the operator's upgrade switch"
        stamp = str(int(time.time()))
        status, _ = _post(addr, PING, stamp)
        assert status == 200, "the stamped scheme still lands"
    finally:
        server.shutdown()


def test_the_sender_stamps_what_it_posts():
    server, state, archive, addr = _server()
    try:
        status = notify_webhook([], f"http://{addr}",
                                signing_key=KEY,
                                payload={"kind": "ping", "n": 7})
        assert status == "200"
        assert state.received == 1
        row = json.loads(archive.read_text().splitlines()[0])
        assert row["scheme"] == "timestamped", \
            "the sender's stamp rode the whole channel"
    finally:
        server.shutdown()


def test_a_rate_refused_attempt_claims_nothing():
    server, state, _archive, addr = _server(max_rate=1,
                                            rate_window=1.0)
    try:
        stamp = str(int(time.time()))
        status, _ = _post(addr, PING, stamp)
        assert status == 200
        other = b'{"kind": "ping", "n": 2}'
        status, _ = _post(addr, other, stamp)
        assert status == 429, "the second post eats the cap"
        # its signature was never claimed - the honest retry
        # (same bytes, after the wait) must land fresh
        time.sleep(1.05)
        status, _data = _post(addr, other, stamp)
        assert status == 200 and state.received == 2, \
            "a 429 does not poison the retry"
    finally:
        server.shutdown()


def test_distinct_posts_never_false_replay():
    server, state, _archive, addr = _server()
    try:
        stamp = str(int(time.time()))
        for i in range(30):
            body = f'{{"kind": "ping", "n": {i}}}'.encode()
            status, _ = _post(addr, body, stamp)
            assert status == 200, f"post {i} lost"
        assert state.received == 30
        assert state.duplicates == 0
    finally:
        server.shutdown()


def test_the_seen_cache_is_bounded():
    server, state, _archive, addr = _server()
    try:
        stamp = str(int(time.time()))
        for i in range(REPLAY_CACHE_MAX + 10):
            body = f'{{"kind": "ping", "n": {i}}}'.encode()
            _post(addr, body, stamp)
        assert state.received == REPLAY_CACHE_MAX + 10
        assert len(state._seen) == REPLAY_CACHE_MAX, \
            "the window's memory is bounded, not a flood mirror"
    finally:
        server.shutdown()


def test_the_window_has_a_floor():
    _server_obj, state, _a, _addr = _server(replay_window=0)
    assert state.replay_window == 1.0, \
        "a zero window would accept only the present second"
    _server_obj.shutdown()


def test_health_names_the_duplicates_counter():
    server, _state, _archive, addr = _server()
    try:
        host, port = addr.split(":")
        conn = HTTPConnection(host, int(port), timeout=10)
        conn.request("GET", "/health")
        data = json.loads(conn.getresponse().read())
        conn.close()
        assert "duplicates" in data, \
            "the ops surface carries the new counter"
    finally:
        server.shutdown()


def test_the_stats_counter_is_exposed():
    server, _state, _archive, addr = _server()
    try:
        stamp = str(int(time.time()))
        _post(addr, PING, stamp)
        _post(addr, PING, stamp)  # echo
        host, port = addr.split(":")
        conn = HTTPConnection(host, int(port), timeout=10)
        conn.request("GET", "/stats")
        data = json.loads(conn.getresponse().read())
        conn.close()
        assert data["duplicates"] == 1
        assert data["received"] == 1
    finally:
        server.shutdown()


def test_the_serve_door_carries_the_new_knobs():
    import inspect

    from approximately import receiver as _rx

    params = inspect.signature(_rx.serve).parameters
    assert "replay_window" in params and "allow_legacy" in params
    from approximately.cli import build_parser

    parser = build_parser()
    argv = parser.parse_args(
        ["webhook-serve", "--replay-window", "45",
         "--require-timestamp", "--store", "x"])
    assert argv.replay_window == 45.0
    assert argv.require_timestamp is True
    argv2 = parser.parse_args(["webhook-serve", "--store", "x"])
    assert argv2.replay_window == 300.0
    assert argv2.require_timestamp is False, \
        "the defaults stay tolerant of pre-4.2 senders"


def test_the_banner_announces_the_nondefault_caps():
    import argparse

    from approximately.cli import _serve_banner

    args = argparse.Namespace(
        max_bytes=1_048_576, max_rows=100_000, rate=0,
        rate_window=60.0, replay_window=45.0,
        require_timestamp=True)
    out = _serve_banner(args, "127.0.0.1", 8080,
                        Path("webhook-log.jsonl"), True)
    assert "replay-window 45s" in out
    assert "legacy refused" in out
    default = _serve_banner(
        argparse.Namespace(max_bytes=1_048_576, max_rows=100_000,
                           rate=0, rate_window=60.0), "127.0.0.1",
        8080, Path("w.jsonl"), False)
    assert "replay-window" not in default, (
        "defaults stay silent - the banner names only the "
        "knobs the operator turned")
