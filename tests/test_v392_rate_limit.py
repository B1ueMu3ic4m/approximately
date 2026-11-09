"""v392: the receiver can say "slow down" in the sender's own
dialect.

An unbounded receiver is a denial target twice over: a flood of
posts fills the archive (max-rows already rotates) and eats the
box's CPU. The receiver can now cap accepted posts per rolling
minute (--rate, 0 = unlimited) — and the gate consumes budget
only for posts that survived every earlier check, so garbage
cannot buy a denial against honest senders. The refusal is 429
with Retry-After: the sender's own retry loop already honors
exactly that signal (bounded backoff), so both ends speak the
same protocol and nobody needed a new word.
"""

import hashlib
import hmac as _hmac
import tempfile
import time
import urllib.request
from pathlib import Path

from approximately.receiver import ReceiverState, serve

KEY = b"rate-key"


def _receiver(max_rate=2):
    archive = Path(tempfile.mkdtemp()) / "webhook-log.jsonl"
    server, state = serve(archive, key=KEY, port=0,
                          max_rate=max_rate)
    port = server.server_address[1]
    return server, state, archive, f"http://127.0.0.1:{port}"


def _post(url, body=b'{"kind": "ping"}', key=KEY):
    sig = "sha256=" + _hmac.new(key, body,
                                hashlib.sha256).hexdigest()
    request = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": "application/json",
                 "X-Approximately-Signature": sig})

    class NoRetry(urllib.request.HTTPHandler):
        def http_open(self, req):
            return super().http_open(req)

    opener = urllib.request.build_opener()
    try:
        with opener.open(request, timeout=10) as response:
            return response.status, dict(response.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers)


def test_the_cap_answers_429_with_retry_after():
    server, state, archive, url = _receiver(max_rate=2)
    try:
        assert _post(url)[0] == 200
        assert _post(url)[0] == 200
        status, headers = _post(url)
        assert status == 429
        assert int(headers.get("Retry-After", 0)) >= 1, \
            "the refusal says when to come back"
        assert state.received == 2 and state.refused == 1
        assert state.throttled == 1, \
            "the throttle names itself - tuning --rate needs \
to see the pressure it applies"
        rows = archive.read_text().splitlines()
        assert len(rows) == 2, \
            "the refused post never reaches the archive"
    finally:
        server.shutdown()


def test_the_gate_consumes_budget_only_for_survivors():
    # two refusals (bad signature) must not spend the honest
    # sender's budget
    server, _state, _archive, url = _receiver(max_rate=2)
    try:
        assert _post(url, key=b"wrong-key")[0] == 401
        assert _post(url, key=b"wrong-key")[0] == 401
        assert _post(url)[0] == 200
        assert _post(url)[0] == 200
        assert _post(url)[0] == 429, \
            "garbage bought nothing; the honest posts did"
    finally:
        server.shutdown()


def test_zero_means_unlimited():
    server, state, _archive, url = _receiver(max_rate=0)
    try:
        for _ in range(5):
            assert _post(url)[0] == 200
        assert state.received == 5
    finally:
        server.shutdown()


def test_the_window_reopens():
    server, state, _archive, url = _receiver(max_rate=1)
    try:
        assert _post(url)[0] == 200
        assert _post(url)[0] == 429
        # the window is 60s of real time — too long to sleep in a
        # test, so the stamp bookkeeping is squeezed directly
        with state.lock:
            state.post_stamps = [time.time() - 61.0]
        assert _post(url)[0] == 200, \
            "a stamp that left the window frees the budget"
    finally:
        server.shutdown()


def test_the_state_helper_is_honest():
    state = ReceiverState(Path(tempfile.mkdtemp())
                          / "webhook-log.jsonl",
                          key=KEY, max_rate=2)
    now = time.time()
    assert state.rate_admit(now) == (True, 0)
    assert state.rate_admit(now) == (True, 0)
    ok, retry = state.rate_admit(now)
    assert ok is False and retry >= 1
    assert state.rate_admit(now + 61.0)[0] is True, \
        "stamps that left the window free the budget"
