"""v190: triage verdicts normalize — one word, one casing.

`Confirmed` and `confirmed` used to be two different verdicts: the
annotation stored verbatim, the `--verdict` filter compared exactly,
and the coverage tally only matched the lower-case idiom. Writes now
normalize (strip + lower) and filters compare case-insensitively, so
the triage workflow reads one word however it was typed.
"""

import argparse
import json

from approximately.cli import _status_payload, cmd_annotations
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _store_with_pretty_verdict(directory):
    store = TraceStore(directory)
    rec = Recorder("the run", save=False)
    rec.respond("done", success=False)
    store.save(rec.trace)
    store.annotate(rec.trace.id, "looked", author="op",
                   verdict="Confirmed")  # pretty-cased on write
    return store, rec.trace.id


def test_write_normalizes_verdict(tmp_path):
    store, tid = _store_with_pretty_verdict(tmp_path)
    entry = store.annotations(tid)[0]
    assert entry["verdict"] == "confirmed"


def test_filter_is_case_insensitive(tmp_path, capsys):
    store, tid = _store_with_pretty_verdict(tmp_path)
    # an old pretty-cased row written before normalization still
    # matches a lower-case filter
    path = store.directory / "annotations.jsonl"
    rows = path.read_text(encoding="utf-8").splitlines()
    row = json.loads(rows[0])
    row["verdict"] = "Confirmed"
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")
    args = argparse.Namespace(store=str(store.directory),
                              trace=tid, verdict="confirmed",
                              json=True)
    assert cmd_annotations(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert len(payload) == 1


def test_coverage_counts_pretty_cased_confirmed(tmp_path):
    store, _ = _store_with_pretty_verdict(tmp_path)
    payload = _status_payload(store, store.list_traces(), None, None)
    # the annotated failure is confirmed regardless of casing
    assert payload["annotations_confirmed"] == 1
    assert payload["triage_coverage"]["ratio"] == 1.0
