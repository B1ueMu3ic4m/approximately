"""v368: the ledger audits itself.

The consistency audit that found the night's duplicate entry
numbers (444, 474) and the 475 gap was a hand-run script. It is a
test now: PLAN entry numbers are unique and gapless, CHANGELOG
heads are unique and newest-first, and the CHANGELOG head matches
pyproject's version. The ledger cannot silently rot again.
"""

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]


def _plan_entries():
    text = (_ROOT / "docs" / "PLAN.md").read_text(encoding="utf-8")
    return [(int(n), v)
            for n, v in re.findall(r"^(\d+)\.\s+\*\*(v[\d.]+)",
                                   text, re.M)]


def test_plan_numbers_are_unique_and_sequential():
    nums = [n for n, _ in _plan_entries()]
    dupes = sorted({n for n in nums if nums.count(n) > 1})
    assert not dupes, f"duplicate entry numbers: {dupes}"
    # the historical tail may have legacy gaps (417/421 fell to
    # re-runs long ago); the pinned era — 444 onward, the first
    # entry this repo's own CI chain numbered — is gapless
    modern = [n for n in nums if n >= 444]
    gaps = [n for n in range(modern[0], modern[-1] + 1)
            if n not in set(modern)]
    assert not gaps, f"gaps in the modern ledger: {gaps}"


def test_changelog_heads_are_unique_and_newest_first():
    from itertools import pairwise

    text = (_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    heads = re.findall(r"^## (v[\d.]+)", text, re.M)
    dupes = sorted({h for h in heads if heads.count(h) > 1})
    assert not dupes, f"duplicate changelog heads: {dupes}"

    def key(h):
        return tuple(int(x) for x in h[1:].split("."))

    assert all(key(a) > key(b) for a, b in pairwise(heads)), (
        "the changelog is not newest-first")


def test_changelog_head_matches_pyproject():
    text = (_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    head = re.findall(r"^## (v[\d.]+)", text, re.M)[0]
    pyproject = re.search(r'version = "([\d.]+)"',
                          (_ROOT / "pyproject.toml").read_text(
                              encoding="utf-8"), re.M).group(1)
    assert head == f"v{pyproject}", \
        f"changelog head {head} != pyproject {pyproject}"
