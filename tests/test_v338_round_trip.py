"""v338: the signed channel, end to end.

Poster and receiver were each tested against stand-in servers; this
closes the loop with the real pair. ``notify_webhook`` (the same
door fleet/tail/spool/digest post through) fires at a live
``webhook-serve`` receiver: the derived fleet payload lands
verified, a forged key is refused 401 with nothing archived, and
the CLI digest door posts its page through the same key from the
environment — the loop approximately talks to itself with.
"""

import json
import tempfile
import time
from http.client import HTTPConnection
from pathlib import Path

from approximately.cli import cmd_digest
from approximately.fleet import notify_webhook, survey
from approximately.receiver import serve
from approximately.recorder import Recorder
from approximately.store import TraceStore

KEY = b"round-trip-sekrit"


def _receiver():
    archive = Path(tempfile.mkdtemp()) / "webhook-log.jsonl"
    server, _state = serve(archive, port=0, key=KEY)
    url = f"http://127.0.0.1:{server.server_address[1]}"
    return server, archive, url


def _stats(url):
    host, port = url[len("http://"):].split(":")
    conn = HTTPConnection(host, int(port), timeout=10)
    conn.request("GET", "/stats")
    resp = conn.getresponse()
    data = json.loads(resp.read())
    conn.close()
    return data


def _failing_store():
    store = TraceStore(tempfile.mkdtemp())
    rec = Recorder("rt-broken", store=store, save=False)
    rec.tool("sh", {}, result="boom")
    rec.respond("done", success=False)
    rec.trace.created_at = int(time.time())
    store.save(rec.trace)
    return store


def test_fleet_payload_lands_verified():
    server, archive, url = _receiver()
    store = _failing_store()
    try:
        status = notify_webhook(survey([store.directory]), url,
                                signing_key=KEY)
        assert status == "200"
        rows = [json.loads(line) for line in
                archive.read_text(encoding="utf-8").splitlines()]
        assert len(rows) == 1
        assert rows[0]["verified"] is True
        assert rows[0]["kind"] == "fleet_summary", \
            "the fleet poster finally says what it is"
        stats = _stats(url)
        assert stats["archive"]["rows"] == 1
        assert stats["archive"]["verified"] == 1
    finally:
        server.shutdown()


def test_forged_key_is_refused_with_nothing_archived():
    server, archive, url = _receiver()
    try:

        status = notify_webhook(
            survey([_failing_store().directory]), url,
            signing_key=b"wrong-key")
        assert status == "HTTP 401", \
            "a forgery is a definite answer, not a retry"
        assert not archive.exists()
        assert _stats(url)["archive"]["rows"] == 0
    finally:
        server.shutdown()


def test_cli_digest_posts_its_page_through_the_env_key(tmp_path,
                                                       monkeypatch,
                                                       capsys):
    server, archive, url = _receiver()
    store = _failing_store()
    monkeypatch.setenv("APPROXIMATELY_SIGNING_KEY", KEY.decode())
    import argparse

    args = argparse.Namespace(
        store=str(store.directory), stores=None, digest_dir=None,
        triage_top=5, grade_floor=None, since_days=1, redact=False,
        json=False, out=None, post=url)
    try:
        assert cmd_digest(args) == 0
        assert "posted: HTTP 200" in capsys.readouterr().out
        rows = [json.loads(line) for line in
                archive.read_text(encoding="utf-8").splitlines()]
        assert len(rows) == 1
        assert rows[0]["verified"] is True
        assert rows[0]["kind"] == "ops_digest"
        assert "markdown" in rows[0]["payload"]
    finally:
        server.shutdown()
