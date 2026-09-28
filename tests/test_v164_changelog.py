"""v164: `approximately changelog` — the ledger becomes the changelog.

docs/PLAN.md is the single source of truth for what shipped; the
new command renders it as a standard changelog, newest first, one
section per version (early versions shipped several items each —
bodies merge). The committed CHANGELOG.md is pinned against a fresh
render, so it cannot drift from the plan.
"""

import argparse

from approximately.changelog import parse_plan, write_changelog
from approximately.cli import cmd_changelog


def test_parse_orders_newest_first():
    from pathlib import Path

    entries = parse_plan(Path("docs/PLAN.md"))
    assert len(entries) > 100
    versions = [v for v, _, _ in entries]
    assert versions[0] == "v1.54"
    assert versions[-1] == "v0.30"
    assert versions == sorted(versions, key=lambda v: [int(x) for x
                                                       in v[1:].split(".")],
                              reverse=True)


def test_write_and_render(tmp_path):
    plan = tmp_path / "PLAN.md"
    plan.write_text(
        "intro\n\n"
        "2. **v0.2 - second** ✅ (delivered): body two.\n\n"
        "1. **v0.1 - first** ✅ (delivered): body one,\n"
        "   wrapped.\n\n"
        "3. **v0.1 - also first** ✅ (delivered): extra.\n",
        encoding="utf-8")
    out = tmp_path / "CHANGELOG.md"
    count = write_changelog(plan, out)
    assert count == 3
    text = out.read_text(encoding="utf-8")
    assert text.index("## v0.2") < text.index("## v0.1")
    assert "body two." in text
    assert "body one, wrapped." in text
    assert "extra." in text


def test_cli_changelog(tmp_path, capsys):
    target = tmp_path / "CHANGELOG.md"
    args = argparse.Namespace(output=str(target),
                              plan="docs/PLAN.md", json=False)
    assert cmd_changelog(args) == 0
    assert "wrote" in capsys.readouterr().out
    assert "## v1.54" in target.read_text(encoding="utf-8")


def test_cli_changelog_missing_plan(tmp_path, capsys):
    args = argparse.Namespace(output=str(tmp_path / "c.md"),
                              plan=str(tmp_path / "nope.md"),
                              json=False)
    assert cmd_changelog(args) == 2
    assert "no PLAN ledger" in capsys.readouterr().err
