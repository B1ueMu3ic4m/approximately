"""v258: `python -m approximately` is the same door as the script.

A package without a `__main__.py` fails the most common habit in
Python — and the failure only shows up outside the test process.
Pinned with a real subprocess.
"""

import pathlib
import subprocess
import sys


def test_module_form_prints_the_version():
    import os

    repo_src = str(
        pathlib.Path(__file__).resolve().parent.parent / "src")
    env = dict(os.environ, PYTHONPATH=repo_src)
    r = subprocess.run(
        [sys.executable, "-X", "utf8", "-m", "approximately",
         "--version"],
        capture_output=True, text=True, timeout=60, env=env)
    assert r.returncode == 0
    assert "2." in r.stdout


def test_module_form_runs_a_real_door():
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        missing = pathlib.Path(tmp) / "no-traces-here"
        missing.mkdir()
        r = subprocess.run(
            [sys.executable, "-X", "utf8", "-m", "approximately",
             "ci", "--store", str(missing),
             "--max-tokens", "10"],
            capture_output=True, text=True, timeout=60)
    # an empty store is refused loudly (exit 2) through the module
    # form — platform-stable by contract
    assert r.returncode == 2
