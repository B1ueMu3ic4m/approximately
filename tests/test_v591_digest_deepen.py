"""v591: the digest names the pattern, and files itself.

A one-off failure is an accident; a mode firing on failures across
two or more distinct days is a PATTERN - the postmortem's headline
is the pattern, not the accident. The digest payload names the
recurring modes (a mode firing on failures across >= 2 distinct
days), the render gives them their own section, and ``--export``
files the whole digest as one markdown document written atomically
- the store.save discipline for every artifact the door writes.
An unwritable parent answers by name (the v5.5.2 convention).
``--export`` is an operator file feature; the MCP surface stays
payload-only (documented scope).
"""

import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _run(*args):
    return subprocess.run(
        [sys.executable, "-m", "approximately", *args],
        capture_output=True, text=True, cwd=str(ROOT))


def _failure(tmp_path, name, task, mode_text, created):
    from approximately.recorder import Recorder
    from approximately.store import TraceStore

    store = TraceStore(tmp_path / name)
    rec = Recorder(task, model="m/1", store=store, save=False)
    rec.tool("deploy", {"env": name}, result=None, error=mode_text)
    rec.respond("done", success=False)
    rec.trace.created_at = created
    store.save(rec.trace)
    return store


def test_a_mode_across_two_days_is_recurring(tmp_path):
    now = time.time()
    _failure(tmp_path, "s", "monday's hang",
             "connection refused - the timeout", now - 3 * 86400)
    _failure(tmp_path, "s", "thursday's hang",
             "connection refused - the timeout", now)
    _failure(tmp_path, "s", "a one-off crash",
             "segfault in plugin", now)
    r = _run("--store", str(tmp_path / "s"), "recall-digest",
             "--json")
    payload = json.loads(r.stdout)
    recurring = {row["mode_id"]: row["days"]
                 for row in payload.get("recurring", [])}
    assert recurring, "the pattern is named in the JSON"
    one_off_days = [row for row in payload.get("recurring", [])
                    if "crash" in row["mode_id"]]
    assert not one_off_days, ("a mode firing once on one day is "
                              "an accident, not a pattern")


def test_the_render_gives_recurring_its_own_section(tmp_path):
    now = time.time()
    _failure(tmp_path, "s", "monday's hang",
             "connection refused - the timeout", now - 3 * 86400)
    _failure(tmp_path, "s", "thursday's hang",
             "connection refused - the timeout", now)
    r = _run("--store", str(tmp_path / "s"), "recall-digest")
    assert "Recurring:" in r.stdout, \
        "the headline is the pattern, not the accident"


def test_a_single_day_mode_is_not_recurring(tmp_path):
    now = time.time()
    _failure(tmp_path, "s", "one bad day",
             "connection refused", now - 3 * 86400)
    _failure(tmp_path, "s", "another that day",
             "connection refused", now - 3 * 86400 + 60)
    r = _run("--store", str(tmp_path / "s"), "recall-digest",
             "--json")
    payload = json.loads(r.stdout)
    assert payload.get("recurring") is None, (
        "two failures on the SAME day are one bad day, not a "
        "recurring pattern")


def test_the_export_files_the_digest_atomically(tmp_path):
    now = time.time()
    _failure(tmp_path, "s", "monday's hang",
             "connection refused - the timeout", now - 3 * 86400)
    _failure(tmp_path, "s", "thursday's hang",
             "connection refused - the timeout", now)
    out = tmp_path / "digest.md"
    r = _run("--store", str(tmp_path / "s"), "recall-digest",
             "--export", str(out))
    assert r.returncode == 0, r.stderr
    text = out.read_text(encoding="utf-8")
    assert "Conversation digest" in text
    assert "Recurring:" in text and "Failures" in text
    assert not list(tmp_path.glob("*.tmp")), \
        "the digest is written atomically"


def test_an_unwritable_export_answers_by_name(tmp_path):
    _failure(tmp_path, "s", "one failure", "boom", time.time())
    out = tmp_path / "missing-dir" / "digest.md"
    r = _run("--store", str(tmp_path / "s"), "recall-digest",
             "--export", str(out))
    assert r.returncode == 2, (
        "the write-error convention holds for the digest: an "
        "unwritable path answers by name")
    assert "error:" in r.stderr and "Traceback" not in r.stderr
