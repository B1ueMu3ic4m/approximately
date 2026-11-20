"""v5930: the README's example commands actually run.

The capability table promises ~40 example commands; a promise
that 404s (or tracebacks) is worse than no promise. This smoke
runs the read-only examples against a seeded store in a sandbox
APPROXIMATELY_HOME — each must exit 0 (or the documented refusal)
with no traceback. Mutating doors (demo, new, init, prices set,
clean, snapshot, webhook-serve) keep their own dedicated pins;
this covers the table's read paths, including the fleet form
(several stores read as one view).
"""

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _run(home, *args):
    env = {**os.environ, "APPROXIMATELY_HOME": str(home)}
    return subprocess.run(
        [sys.executable, "-m", "approximately", *args],
        capture_output=True, text=True, cwd=str(ROOT),
        encoding="utf-8", env=env)


def _seed(home):
    """Three conversations in one box: two ok, one failed."""
    from approximately.recorder import Recorder
    from approximately.store import TraceStore

    store = TraceStore(home)
    for i in range(3):
        rec = Recorder(f"readme run {i} - deploy search",
                       model="m/1", store=store, save=False)
        rec.tool("deploy", {"i": i}, result="ok",
                 latency_ms=100 + i)
        rec.respond("done", success=(i != 2))
        store.save(rec.trace)
    return store


def test_the_readme_examples_run(tmp_path):
    home = tmp_path / "home"
    _seed(home)
    examples = [
        ["recall", "--grep", "deploy"],
        ["recall-summary", "--since", "1w"],
        ["recall-digest"],
        ["verify", "--all"],
        ["query", "success == false"],
        ["stats"],
        ["grade"],
        ["cluster"],
        ["drift"],
        ["explain", "FM-1.3"],
        ["taxonomy"],
        ["anomalies", "latest", "--tokens"],
        ["attribute", "--all", "--sarif",
         str(tmp_path / "alerts.sarif")],
        ["metrics", "--prometheus"],
        ["handoff", "--queue", "5"],
    ]
    for args in examples:
        r = _run(home, *args)
        assert r.returncode == 0, (
            f"{args} rc={r.returncode}: {r.stderr[-300:]}")
        assert "Traceback" not in r.stderr, (
            f"{args} leaked a traceback")


def test_the_examples_answer_against_a_fleet(tmp_path):
    home = tmp_path / "home"
    second = tmp_path / "second"
    _seed(home)
    _seed(second)
    r = _run(home, "verify", str(home), str(second))
    assert r.returncode == 0, r.stderr
    r = _run(home, "recall", str(home), str(second))
    assert r.returncode == 0, r.stderr
    assert "> store:" in r.stdout or "{second}" in r.stdout or \
        "conversation" in r.stdout
    r = _run(home, "recall-summary", str(home), str(second))
    assert r.returncode == 0, r.stderr
    r = _run(home, "recall-digest", str(home), str(second))
    assert r.returncode == 0, r.stderr


def test_the_json_examples_stay_machine_readable(tmp_path):
    home = tmp_path / "home"
    _seed(home)
    for args in (["verify", "--all", "--json"],
                 ["stats", "--json"],
                 ["recall", "--json"]):
        r = _run(home, *args)
        assert r.returncode == 0, r.stderr
        payload = json.loads(r.stdout)
        assert isinstance(payload, (dict, list))
