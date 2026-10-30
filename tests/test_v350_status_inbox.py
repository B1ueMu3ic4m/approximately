"""v350: the one-glance page reads the inbox.

``status`` is the shift's first look; the webhook inbox lived one
`read_archive` away but never showed. The frame gains a line -
rows, verified split - only when the store keeps an archive, in
prose and JSON. Same numbers /stats, digest and fleet answer:
one reader under every surface.
"""

import json
import tempfile

from approximately.cli import _render_status, _status_payload
from approximately.store import TraceStore


def _store(with_archive: bool):
    store = TraceStore(tempfile.mkdtemp())
    if with_archive:
        archive = store.directory / "webhook-log.jsonl"
        rows = [{"received_at": 1.0 + i, "verified": i < 2,
                 "kind": "spool", "payload": {}}
                for i in range(5)]
        with archive.open("a", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row) + "\n")
    return store


def _payload(store):
    return _status_payload(store, store.list_traces(), None)


def test_payload_counts_the_inbox():
    payload = _payload(_store(with_archive=True))
    assert payload["webhook_inbox"] == {
        "present": True, "rows": 5, "verified": 2, "unverified": 3}


def test_absent_archive_is_present_false():
    payload = _payload(_store(with_archive=False))
    assert payload["webhook_inbox"]["present"] is False
    assert payload["webhook_inbox"]["rows"] == 0


def test_prose_line_shows_the_split_only_when_present(capsys):
    import argparse

    busy = _store(with_archive=True)
    out = _render_status(argparse.Namespace(
        store=str(busy.directory), digest_dir=None, since=None,
        json_mode=False, spend_ceiling=None, failure_budget=None,
        prices=None))
    assert "webhook inbox: 5 row(s) (2 verified, 3 unverified)" in out

    quiet = _store(with_archive=False)
    out = _render_status(argparse.Namespace(
        store=str(quiet.directory), digest_dir=None, since=None,
        json_mode=False, spend_ceiling=None, failure_budget=None,
        prices=None))
    assert "webhook inbox" not in out
