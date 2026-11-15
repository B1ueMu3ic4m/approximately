"""v511: the release notes are release notes.

The changelog pipeline swallowed the plan's trailing sections
(launch plan, risks & mitigations, references) into the LAST
ledger entry's body — the parser's lookahead ran to end of file —
so every release generated while its entry was last carried the
launch plan, the risk table and the arXiv references inside its
release notes. Planning material is not release notes: the entry
body now ends at the next `## ` section heading, and the pin
guards the fence.
"""

from pathlib import Path

from approximately.changelog import parse_plan

ROOT = Path(__file__).resolve().parent.parent


def test_the_last_entry_stops_at_the_section_boundary():
    entries = parse_plan(ROOT / "docs" / "PLAN.md")
    _version, _title, body = entries[0]
    assert "Launch plan" not in body, \
        "the launch plan is planning material, not release notes"
    assert "Risks & mitigations" not in body
    assert "References" not in body
    import re

    assert not re.search(r"^## ", body, re.M), \
        "no markdown section heading rides an entry body"


def test_the_changelog_carries_no_planning_sections():
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    for marker in ("## 4. Launch plan", "## 5. Risks",
                   "## 6. References"):
        assert marker not in text, \
            f"{marker!r} rode the changelog through the parser"


def test_entry_bodies_elsewhere_are_untouched():
    entries = parse_plan(ROOT / "docs" / "PLAN.md")
    versions = {v for v, _t, _b in entries}
    assert {"v5.1.0", "v5.0.0", "v4.2.0"} <= versions, \
        "the boundary change must not drop any delivered entry"
