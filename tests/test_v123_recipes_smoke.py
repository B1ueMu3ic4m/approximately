"""v123: RECIPES smoke — the cookbook's walkthrough must stay true.

Sections 1-4 of RECIPES.md (record -> attribute -> explain -> bisect
-> regression guard) executed end-to-end against a real temp store
via the CLI, exactly as the docs show them. When a recipe drifts
from the code, this pins which line broke.
"""

import subprocess
import sys

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
    from approximately.integrity import sign

    ok = Recorder("healthy run", save=False)
    ok.trace.id = "good-1"
    ok.tool("search", {"route": "SFO-NRT"}, result="$880")
    ok.respond("booked JT-044", success=True)
    sign(ok.trace)
    store.save(ok.trace)
    bad = Recorder("book the flight", save=False)
    bad.trace.id = "bad-1"
    bad.tool("search", {"route": "SFO-NRT"}, result="$880")
    bad.tool("book", {"seat": "12A"}, result=None, error="timeout")
    bad.respond("gave up", success=False)
    sign(bad.trace)
    store.save(bad.trace)
    return store


@pytest.mark.skipif(sys.version_info < (3, 10),
                    reason="walkthrough runs on the modern interpreter")
def test_recipe_attribute_explain_bisect(store):
    """RECIPES §3: attribute --explain, explain <mode>, bisect."""
    attr = _cli("attribute", "bad-1", "--store", str(store.directory),
                "--explain")
    assert attr.returncode == 0, attr.stderr
    exp = _cli("explain", "FM-1.3")
    assert exp.returncode == 0, exp.stderr
    assert "FM-1.3" in exp.stdout
    bisect = _cli("bisect", "bad-1", "good-1",
                  "--store", str(store.directory))
    assert bisect.returncode in (0, 1), bisect.stderr


@pytest.mark.skipif(sys.version_info < (3, 10),
                    reason="walkthrough runs on the modern interpreter")
def test_recipe_regression_guard_runs(store, tmp_path):
    """RECIPES §4: `test <id>` mints a pytest file that collects."""
    out = tmp_path / "test_guard.py"
    gen = _cli("test", "bad-1", "--store", str(store.directory),
               "--output", str(out))
    assert gen.returncode == 0, gen.stderr
    assert out.exists()
    collected = subprocess.run(
        [sys.executable, "-m", "pytest", str(out), "--collect-only", "-q"],
        capture_output=True, text=True)
    assert collected.returncode == 0, collected.stderr
    assert "test_" in collected.stdout


@pytest.mark.skipif(sys.version_info < (3, 10),
                    reason="walkthrough runs on the modern interpreter")
def test_recipe_status_and_verify(store):
    """RECIPES' ops pair: `verify <id>` and `status` both succeed."""
    verify = _cli("verify", "bad-1", "--store", str(store.directory))
    assert verify.returncode == 0, verify.stderr
    status = _cli("status", "--store", str(store.directory))
    assert status.returncode == 0, status.stderr
    assert "1 traces, 1 failed" in status.stdout
    assert "last failure: bad-1" in status.stdout
