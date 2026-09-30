"""v193: docs health as a permanent test, not a manual audit.

Every relative Markdown link in README/docs must resolve to a real
file (the v1.15 link audit, automated), and the version claims that
matter must stay fresh: CHANGELOG's newest section and PLAN's newest
item both track `pyproject.toml`. Since v2.0 the README is a
description, not a release log — per-version entries live in
CHANGELOG.md and on the Releases page, and a pin keeps it that way.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _md_files():
    yield ROOT / "README.md"
    for path in sorted((ROOT / "docs").glob("*.md")):
        yield path


def test_every_relative_link_resolves():
    broken = []
    for path in _md_files():
        for match in re.finditer(r"\]\(([^)#]+?)(#[^)]*)?\)",
                                 path.read_text(encoding="utf-8")):
            target = match.group(1)
            if target.startswith(("http://", "https://", "mailto:")):
                continue
            if not (path.parent / target).is_file():
                broken.append(f"{path.name}: {target}")
    assert broken == [], broken



def _version_key(version: str):
    parts = tuple(int(p) for p in re.findall(r"\d+", version))
    return parts + (0,) * (3 - len(parts)) if len(parts) < 3 else parts


def test_changelog_newest_tracks_pyproject():
    expected = re.search(r'^version = "(.+?)"',
                         (ROOT / "pyproject.toml").read_text(
                             encoding="utf-8"),
                         re.M).group(1)
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    # PLAN headings use short versions (v1.93); pyproject is 1.93.0
    key = _version_key(f"v{expected}")
    # the changelog is newest-first: the FIRST section is the release
    first = re.search(r"^## v([\d.]+)", changelog, re.M)
    assert first is not None
    assert _version_key(first.group(1)) == key


def test_readme_stays_version_lean():
    # v2.0 policy: the README describes the project; per-version
    # entries live in CHANGELOG.md and on the Releases page. The old
    # 100+-row roadmap crept to 400+ lines — this pin keeps it out.
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    rows = re.findall(r"- ✅ \*\*(v[\d.]+)\*\*", readme)
    assert rows == [], f"per-version rows crept back into README: {rows[-3:]}"


def test_plan_newest_item_tracks_pyproject():
    from approximately.changelog import parse_plan

    expected = re.search(r'^version = "(.+?)"',
                         (ROOT / "pyproject.toml").read_text(
                             encoding="utf-8"),
                         re.M).group(1)
    entries = parse_plan(ROOT / "docs" / "PLAN.md")
    assert _version_key(entries[0][0]) == _version_key(f"v{expected}")
