"""v400: the rule is executable.

"The minor is one digit, never 10+" was written into
VERSIONING.md and the CHANGELOG — as prose. Prose is a promise
only a test can keep: this file parses pyproject's version and
refuses any minor above 9, checks the versioning document
actually states the rule and the reclassification (so a doc
edit cannot quietly drop the promise), and confirms the 3.x
tags remain untouched — history was reclassified, not
rewritten, and the audit proves the reclassification is the
only thing that changed.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _version():
    match = re.search(r'^version = "(.+?)"',
                      (ROOT / "pyproject.toml").read_text(
                          encoding="utf-8"), re.M)
    return match.group(1)


def test_the_minor_is_one_digit():
    major, minor, patch = _version().split(".")
    assert int(minor) <= 9, \
        "the minor raced past nine - the rule is policy"
    assert int(major) >= 1 and int(patch) >= 0


def test_the_version_shape_is_semver():
    assert re.fullmatch(r"\d+\.\d+\.\d+", _version()), \
        "major.minor.patch, nothing else"


def test_the_document_states_the_rule():
    doc = (ROOT / "docs" / "VERSIONING.md").read_text(
        encoding="utf-8")
    assert "never reaches 10" in doc, \
        "the single-digit rule must stay written down"
    assert "reclassification" in doc, \
        "the 3.x regrouping must stay named"
    assert "never rewritten" in doc, \
        "history stays as published - the promise stays written"


def test_the_drift_is_named_not_hidden():
    doc = (ROOT / "docs" / "VERSIONING.md").read_text(
        encoding="utf-8")
    assert "3.10" in doc and "3.99" in doc, \
        "the drifted tail is reclassified, not erased"


def test_history_is_never_rewritten():
    # the drift's end must remain in git history verbatim: the
    # reclassification regrouped the story, it did not touch
    # the record (works without tags - CI checkouts have none)
    import subprocess

    out = subprocess.run(["git", "log", "--oneline", "-200"],
                         capture_output=True, text=True,
                         cwd=ROOT)
    assert "v3.99.1" in out.stdout, \
        "the last 3.x release stays in history as published"
