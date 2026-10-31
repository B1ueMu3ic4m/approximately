"""v361: the fleet survey counts the inbox.

The fleet page's per-store line grew the webhook inbox: rows and
the verified split, read through the one reader — silent when a
store keeps no archive, honest when it does. The JSON payload
carries the same counts.
"""

import json
import tempfile

from approximately.cli import _print_fleet
from approximately.fleet import survey
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _store(with_archive: bool):
    store = TraceStore(tempfile.mkdtemp())
    rec = Recorder("kept", store=store)
    rec.tool("sh", {}, result="ok")
    rec.respond("done", success=True)
    store.save(rec.trace)
    if with_archive:
        archive = store.directory / "webhook-log.jsonl"
        with archive.open("a", encoding="utf-8") as fh:
            for i in range(3):
                fh.write(json.dumps({"received_at": 1.0 + i,
                                     "verified": i == 0,
                                     "kind": "spool",
                                     "payload": {}}) + "\n")
    return store


def test_survey_carries_the_counts(capsys):
    busy = _store(with_archive=True)
    quiet = _store(with_archive=False)
    summaries = survey([busy.directory, quiet.directory])
    _print_fleet(summaries)
    out = capsys.readouterr().out
    assert out.count("webhook inbox: 3 row(s), 1 verified") == 1, \
        "one line, only for the store with an archive"
    by_rows = [s.inbox_rows for s in summaries]
    assert sorted(by_rows) == [0, 3]


def test_json_payload_shape_stays_honest(capsys):
    busy = _store(with_archive=True)
    summaries = survey([busy.directory])
    assert summaries[0].inbox_rows == 3
    assert summaries[0].inbox_verified == 1


def test_the_html_dashboard_carries_it_too():
    from approximately.fleet import render_fleet_html

    busy = _store(with_archive=True)
    quiet = _store(with_archive=False)
    page = render_fleet_html(survey([busy.directory,
                                     quiet.directory]))
    assert page.count("webhook inbox: 3 row(s), 1 verified") == 1, \
        "the fourth fleet surface shows the inbox as well"


def test_the_payload_carries_the_counts_to_the_channel():
    from approximately.fleet import webhook_payload

    busy = _store(with_archive=True)
    quiet = _store(with_archive=False)
    payload = webhook_payload(survey([busy.directory,
                                      quiet.directory]))
    rows = {s["name"]: s.get("inbox_rows") for s in payload["stores"]}
    verified = {s["name"]: s.get("inbox_verified")
                for s in payload["stores"]}
    assert sorted(v for v in rows.values() if v is not None) == \
        [0, 3], "the counts ride to the receiver and the trend"
    assert 1 in verified.values()
