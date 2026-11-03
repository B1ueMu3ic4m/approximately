"""v369: every "recipe N" citation points at a real chapter.

TUTORIAL and RECIPES cross-reference each other by chapter number
("(recipe 18)"); renumbering a chapter silently rots those
citations. This test extracts every cited number from the docs
and holds it against the chapters RECIPES actually has.
"""

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]


def _recipes_headings():
    text = (_ROOT / "docs" / "RECIPES.md").read_text(
        encoding="utf-8")
    return {int(m.group(1))
            for m in re.finditer(r"^## (\d+)\.", text, re.M)}


def _cited_numbers():
    cited = set()
    for doc in ("docs/TUTORIAL.md", "docs/RECIPES.md",
                "docs/ARCHITECTURE.md"):
        text = (_ROOT / doc).read_text(encoding="utf-8")
        for m in re.finditer(r"recipe (\d+)", text, re.I):
            cited.add(int(m.group(1)))
    return cited


def test_every_cited_recipe_exists():
    chapters = _recipes_headings()
    cited = _cited_numbers()
    missing = sorted(c for c in cited if c not in chapters)
    assert not missing, \
        f"cited recipes that do not exist: {missing}"


def test_chapters_are_contiguous_from_one():
    chapters = sorted(_recipes_headings())
    assert chapters == list(range(1, len(chapters) + 1)), \
        "recipe chapters have gaps or dupes"
