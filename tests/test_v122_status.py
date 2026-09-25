"""v122: `approximately status` — the daily-driver ops overview.

One command answers "how is this store doing right now": totals and
failure rate, top failure modes, triage tallies (annotations and how
many confirmed), and the most recent failing trace with its evidence
chain verdict. `--json` for dashboards; `--since` scopes the window.
"""

import argparse
import json

from approximately.cli import build_parser, cmd_status
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _store(tmp_path):
    store = TraceStore(str(tmp_path / "s"))
    rec = Recorder("ok run", save=False)
    rec.trace.id = "ok-1"
    rec.respond("done", success=True)
    store.save(rec.trace)
    bad = Recorder("book the flight", save=False)
    bad.trace.id = "bad-1"
    bad.tool("book", {"seat": "12A"}, result=None, error="timeout")
    bad.respond("gave up", success=False)
    store.save(bad.trace)
    store.annotate("bad-1", "infra timeout", author="oncall",
                   verdict="confirmed")
    return store


def test_status_json_payload(tmp_path, capsys):
    store = _store(tmp_path)
    args = argparse.Namespace(store=str(store.directory), json=True,
                              since=None)
    assert cmd_status(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["traces"] == 2
    assert payload["failures"] == 1
    assert payload["failure_rate"] == 0.5
    assert payload["annotations"] == 1
    assert payload["annotations_confirmed"] == 1
    assert payload["last_failure"]["id"] == "bad-1"
    assert payload["last_failure"]["chain"] == "unsigned"


def test_status_text_renders_overview(tmp_path, capsys):

    store = _store(tmp_path)
    args = build_parser().parse_args(
        ["status", "--store", str(store.directory)])
    assert args.func(args) == 0
    out = capsys.readouterr().out
    assert "2 traces, 1 failed (50%)" in out
    assert "annotations: 1 (1 confirmed)" in out
    assert "last failure: bad-1" in out


def test_status_empty_store(tmp_path, capsys):
    store = TraceStore(str(tmp_path / "empty"))
    args = argparse.Namespace(store=str(store.directory), json=True,
                              since=None)
    assert cmd_status(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["traces"] == 0
    assert payload["last_failure"] is None
    assert payload["annotations"] == 0


def test_fleet_survey_carries_triage_tallies(tmp_path):
    """v0.96: the fleet dashboard and webhook know each store's
    annotation activity - notes/confirmed ride on StoreSummary."""
    from approximately.fleet import survey, webhook_payload

    store = _store(tmp_path)
    summaries = survey([store.directory])
    assert summaries[0].annotations == 1
    assert summaries[0].annotations_confirmed == 1
    payload = webhook_payload(summaries)["stores"][0]
    assert payload["annotations"] == 1
    assert payload["annotations_confirmed"] == 1


def test_status_with_trend(tmp_path, capsys):
    """v1.1: `status --digest-dir` reports the fleet trend verdict."""
    from approximately.fleet import append_digest, digest_snapshot, survey

    store = _store(tmp_path)
    digests = tmp_path / "digests"
    digests.mkdir()
    append_digest(digests, digest_snapshot(survey([store.directory])))
    args = argparse.Namespace(store=str(store.directory), json=True,
                              since=None, digest_dir=str(digests))
    assert cmd_status(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["trend"] and payload["trend"]["verdict"]
