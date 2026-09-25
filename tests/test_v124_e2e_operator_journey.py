"""v124: the operator journey, end to end, through the real CLI.

One subprocess-driven test walks the whole story a user lives:
record two agents' runs (one fails) -> attribute -> report (HTML +
Markdown) -> cluster -> mint a regression guard -> annotate ->
status -> verify --all -> fleet survey -> digest -> trend. Exit
codes chain; each hand-off is the seam a regression would break.
"""

import subprocess
import sys
from pathlib import Path

import pytest

from approximately.recorder import Recorder
from approximately.store import TraceStore


def _cli(*args):
    return subprocess.run(
        [sys.executable, "-m", "approximately.cli", *args],
        capture_output=True, text=True)


@pytest.fixture()
def store(tmp_path):
    store = TraceStore(str(tmp_path / "traces"))
    good = Recorder("healthy booking run", save=False)
    good.trace.id = "journey-good"
    good.tool("search", {"route": "SFO-NRT"}, result="$880")
    good.respond("booked JT-044", success=True)
    store.save(good.trace)

    bad = Recorder("book the flight", save=False)
    bad.trace.id = "journey-bad"
    bad.tool("search", {"route": "SFO-NRT"}, result="$880",
             agent="searcher")
    bad.tool("book", {"seat": "12A"}, result=None, error="timeout",
             agent="booker")
    bad.respond("gave up", success=False, agent="booker")
    store.save(bad.trace)
    return store


@pytest.mark.skipif(sys.version_info < (3, 10),
                    reason="walkthrough runs on the modern interpreter")
def test_full_operator_journey(store, tmp_path):
    digs = tmp_path / "digests"
    digs.mkdir()

    # 1. attribute: the failing trace gets a verdict
    attr = _cli("attribute", "journey-bad", "--store",
                str(store.directory))
    assert attr.returncode == 0, attr.stderr
    assert "FM-" in attr.stdout

    # 2. report: HTML + Markdown land on disk
    report = _cli("report", "journey-bad", "--store",
                  str(store.directory))
    assert report.returncode == 0, report.stderr
    htmls = list(Path(store.directory).glob("journey-bad*.html"))
    assert htmls, "HTML report missing"

    # 3. cluster: the failure groups by mode
    cluster = _cli("cluster", "--store", str(store.directory))
    assert cluster.returncode == 0, cluster.stderr

    # 4. mint a regression guard
    guard = tmp_path / "test_guard.py"
    minted = _cli("test", "journey-bad", "--store",
                  str(store.directory), "--output", str(guard))
    assert minted.returncode == 0, minted.stderr
    assert guard.exists()

    # 5. annotate the human verdict
    ann = _cli("annotate", "journey-bad", "infra timeout",
               "--store", str(store.directory),
               "--author", "oncall", "--verdict", "confirmed")
    assert ann.returncode == 0, ann.stderr

    # 6. status: the pulse knows everything above
    status = _cli("status", "--store", str(store.directory))
    assert status.returncode == 0, status.stderr
    assert "annotations: 1 (1 confirmed)" in status.stdout
    assert "last failure: journey-bad" in status.stdout

    # 7. verify the whole store's evidence
    verify = _cli("verify", "--all", "--store", str(store.directory))
    assert verify.returncode == 0, verify.stdout + verify.stderr

    # 8. fleet survey + digest + trend
    fleet = _cli("fleet", store.directory, "--digest-dir", str(digs),
                 "--iterations", "1", "--watch", "0")
    assert fleet.returncode == 0, fleet.stderr
    trend = _cli("fleet", store.directory, "--trend",
                 "--digest-dir", str(digs))
    assert trend.returncode == 0, trend.stderr
