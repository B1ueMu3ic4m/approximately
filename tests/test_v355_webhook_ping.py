"""v355: `webhook-ping` — prove the channel works.

Setting up the receiver and the poster are two halves of one
config; until now the only way to prove they agreed was to wait
for a real alert. The ping door signs a synthetic post through the
same notify_webhook every other poster uses, then reads the
receiver's archive back — accepted, verified, counted. A ping
without a key tests nothing and is refused.
"""

import argparse
import json
import tempfile
from pathlib import Path

from approximately.cli import cmd_webhook_ping
from approximately.receiver import serve


def _receiver(key=None):
    archive = Path(tempfile.mkdtemp()) / "webhook-log.jsonl"
    server, state = serve(archive, port=0, key=key)
    url = f"http://127.0.0.1:{server.server_address[1]}"
    return server, archive, url


def _args(url, key_file=None, message=None):
    return argparse.Namespace(url=url, key_file=key_file,
                              message=message, store=".")


def test_ping_lands_verified_and_reads_the_archive_back(capsys):
    server, archive, url = _receiver(key=b"ping-key")
    keyfile = Path(tempfile.mkdtemp()) / "key"
    keyfile.write_bytes(b"ping-key")
    try:
        assert cmd_webhook_ping(_args(url, key_file=str(keyfile),
                                      message="hello")) == 0
        out = capsys.readouterr().out
        assert "ping accepted: HTTP 200" in out
        assert "receiver archive: 1 row(s), 1 verified" in out
        rows = [json.loads(line) for line in
                archive.read_text().splitlines()]
        assert rows[0]["verified"] is True
        assert rows[0]["payload"]["message"] == "hello"
    finally:
        server.shutdown()


def test_key_mismatch_is_a_reported_not_a_crash(capsys):
    server, _archive, url = _receiver(key=b"receiver-key")
    keyfile = Path(tempfile.mkdtemp()) / "key"
    keyfile.write_bytes(b"wrong-key")
    try:
        assert cmd_webhook_ping(_args(url, key_file=str(keyfile))
                                ) == 1
        err = capsys.readouterr().err
        assert "ping NOT accepted: HTTP 401" in err
        assert "keys differ" in err
    finally:
        server.shutdown()


def test_no_key_is_a_refusal():
    server, _archive, url = _receiver()
    try:
        assert cmd_webhook_ping(_args(url)) == 2
        assert cmd_webhook_ping(_args("ftp://x")) == 2
    finally:
        server.shutdown()
