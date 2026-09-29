"""v193: docs health as a permanent test, not a manual audit.

Every relative Markdown link in README/docs must resolve to a real
file (the v1.15 link audit, automated), and the version claims that
matter must stay fresh: CHANGELOG's newest section and the README
roadmap's newest row both track `pyproject.toml`.
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


def test_changelog_newest_tracks_pyproject():
    expected = re.search(r'^version = "(.+?)"',
                         (ROOT / "pyproject.toml").read_text(
                             encoding="utf-8"),
                         re.M).group(1)
    short = "v" + ".".join(expected.split(".")[:2])
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    # PLAN headings use short versions (v1.93); pyproject is 1.93.0
    assert f"## {short}" in changelog or f"## v{expected}" in changelog


def test_readme_roadmap_newest_tracks_pyproject():
    expected = re.search(r'^version = "(.+?)"',
                         (ROOT / "pyproject.toml").read_text(
                             encoding="utf-8"),
                         re.M).group(1)
    short = "v" + ".".join(expected.split(".")[:2])
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    rows = re.findall(r"- ✅ \*\*(v[\d.]+)\*\*", readme)
    assert rows, "roadmap rows vanished"
    assert rows[-1] in (f"v{expected}", short)


def test_plan_newest_item_tracks_pyproject():
    from approximately.changelog import parse_plan

    expected = re.search(r'^version = "(.+?)"',
                         (ROOT / "pyproject.toml").read_text(
                             encoding="utf-8"),
                         re.M).group(1)
    entries = parse_plan(ROOT / "docs" / "PLAN.md")
    short = "v" + ".".join(expected.split(".")[:2])
    assert entries[0][0] in (f"v{expected}", short)
