"""v593: the memory journey, end to end.

The e2e operator journey (v124) records, attributes and reports -
but never asks the question the whole feature family exists for:
"two weeks later, what did I talk about with the AI?" This pin
walks the human's actual path over one store: record three
conversations (one failing), find them on the timeline, search
for the moment something was said, read the day summary, drill
into that day, take the digest with its failure modes, and carry
the memory out as files - every step through the installed CLI,
nothing mocked.
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


def test_the_memory_journey(tmp_path):
    store = tmp_path / "s"
    from approximately.recorder import Recorder
    from approximately.store import TraceStore

    ts = TraceStore(store)
    for task, ok, error in (
            ("provision the staging cluster", True, None),
            ("investigate the flaky payment webhook", False,
             "webhook timed out after 3 retries"),
            ("rotate the api keys", True, None)):
        rec = Recorder(task, model="m/1", store=ts, save=False)
        rec.tool("deploy", {"env": task[:8]}, result="ok",
                 error=error)
        rec.respond("done", success=ok)
        ts.save(rec.trace)

    # 1. the timeline: three conversations, one marked failed
    r = _run("--store", str(store), "recall")
    assert r.returncode == 0, r.stderr
    assert "provision the staging cluster" in r.stdout
    assert "✗" in r.stdout, "the failed run is marked in the prose"

    # 2. search finds the moment something was said
    r = _run("--store", str(store), "recall", "--grep", "webhook")
    assert r.returncode == 0, r.stderr
    assert "flaky payment webhook" in r.stdout
    assert "[error]" in r.stdout or "[task]" in r.stdout

    # 3. the day summary aggregates the day
    r = _run("--store", str(store), "recall-summary", "--json")
    payload = json.loads(r.stdout)
    assert payload["conversations"] == 3
    assert payload["failed"] == 1
    day = payload["days"][-1]["day"]

    # 4. the drill-down lands on exactly that day
    r = _run("--store", str(store), "recall", "--day", day,
             "--json")
    payload = json.loads(r.stdout)
    assert payload["conversations"] == 3

    # 5. the digest names the failure and its modes
    r = _run("--store", str(store), "recall-digest")
    assert r.returncode == 0, r.stderr
    assert "Failures (1):" in r.stdout
    assert "webhook timed out" in r.stdout
    assert "modes:" in r.stdout

    # 6. the memory leaves as files
    diary = tmp_path / "diary.md"
    r = _run("--store", str(store), "recall", "--export",
             str(diary))
    assert r.returncode == 0, r.stderr
    assert "provision the staging cluster" in diary.read_text(
        encoding="utf-8")
    digest = tmp_path / "digest.md"
    r = _run("--store", str(store), "recall-digest", "--export",
             str(digest))
    assert r.returncode == 0, r.stderr
    text = digest.read_text(encoding="utf-8")
    assert "Conversation digest" in text
    assert "Failures" in text
    assert not list(tmp_path.glob("*.tmp")), "atomic writes"

    # 7. verify still vouches for the store after all of it
    r = _run("--store", str(store), "verify", "--all")
    assert r.returncode == 0, (
        f"the memory journey must not disturb the evidence: "
        f"{r.stdout[-200:]} {r.stderr[-200:]}")


def test_a_touched_later_store_still_answers(tmp_path):
    store = tmp_path / "s"
    from approximately.recorder import Recorder
    from approximately.store import TraceStore

    ts = TraceStore(store)
    rec = Recorder("later task", model="m/1", store=ts, save=False)
    rec.tool("deploy", {"env": "x"}, result="ok")
    rec.respond("done", success=True)
    rec.trace.created_at = time.time() - 86400
    ts.save(rec.trace)
    r = _run("--store", str(store), "recall", "--since", "1h")
    assert r.returncode == 0 and "later task" not in r.stdout
    r2 = _run("--store", str(store), "recall", "--since", "1w")
    assert "later task" in r2.stdout
