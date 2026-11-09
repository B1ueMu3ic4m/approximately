"""v398: one protocol, tested end to end.

"Both ends speak one protocol" was a design claim: the
receiver's 429 carries Retry-After and the sender's retry honors
it — but the two halves were only ever tested apart, and the
window itself was a hard-coded 60s no test could afford to
sleep through. --rate-window opens the window (default stays a
minute) and the end-to-end test now runs the REAL loop: the
sender's own notify_webhook posts into a rate-capped receiver,
eats a 429, sleeps the Retry-After the receiver named, and
lands the post on the retry — both halves, one conversation,
no mock in sight.
"""

import json
import tempfile
import time
from pathlib import Path

from approximately.fleet import notify_webhook
from approximately.receiver import ReceiverState, serve

KEY = b"window-key"


def _receiver(max_rate=1, rate_window=1.0):
    archive = Path(tempfile.mkdtemp()) / "webhook-log.jsonl"
    server, state = serve(archive, key=KEY, port=0,
                          max_rate=max_rate,
                          rate_window=rate_window)
    port = server.server_address[1]
    return server, state, archive, f"http://127.0.0.1:{port}"


def test_the_window_is_configurable():
    state = ReceiverState(Path(tempfile.mkdtemp())
                          / "webhook-log.jsonl",
                          key=KEY, max_rate=1, rate_window=1.0)
    now = time.time()
    assert state.rate_admit(now) == (True, 0)
    assert state.rate_admit(now + 0.3)[0] is False, \
        "inside the window the budget is spent"
    assert state.rate_admit(now + 1.2)[0] is True, \
        "past the window the budget returns"


def test_both_ends_speak_one_protocol():
    server, state, archive, url = _receiver(max_rate=1,
                                            rate_window=1.0)
    try:
        # the sender's real path: notify_webhook, no mocks —
        # the first post lands, the second eats a 429, honors
        # the Retry-After the receiver named, and lands
        import time as _time

        first = notify_webhook([], url, signing_key=KEY,
                               payload={"kind": "ping",
                                        "n": 1})
        assert first == "200"
        started = _time.monotonic()
        second = notify_webhook([], url, signing_key=KEY,
                                payload={"kind": "ping",
                                         "n": 2})
        elapsed = _time.monotonic() - started
        assert second == "200", \
            "the retry after Retry-After lands"
        assert elapsed >= 1.0, \
            "the sender actually waited the receiver's window"
        rows = [json.loads(line)
                for line in archive.read_text().splitlines()]
        assert [r["payload"]["n"] for r in rows] == [1, 2], \
            "both posts archived, in order, none lost"
        assert state.throttled == 1
    finally:
        server.shutdown()


def test_the_default_window_is_a_minute():
    state = ReceiverState(Path(tempfile.mkdtemp())
                          / "webhook-log.jsonl", key=KEY)
    assert state.rate_window == 60.0


def test_a_sub_second_window_is_refused_at_the_fence():
    state = ReceiverState(Path(tempfile.mkdtemp())
                          / "webhook-log.jsonl", key=KEY,
                          rate_window=0.1)
    assert state.rate_window == 1.0, \
        "a window under a second is a misconfiguration"
