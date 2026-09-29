"""v199: the changelog handles the milestone version (v1.100).

Version sorting must stay correct past v1.99 — tuple comparison puts
v1.100 after v1.99 (numeric parts, not string order), and the
section heading renders verbatim.
"""


from approximately.changelog import parse_plan, render


def test_three_part_versions_sort_numerically(tmp_path):
    plan = tmp_path / "PLAN.md"
    plan.write_text(
        "1. **v1.99 - ninety-nine** ✅ (delivered): b\n"
        "2. **v1.100 - one hundred** ✅ (delivered): a\n",
        encoding="utf-8")
    entries = parse_plan(plan)
    assert [v for v, _, _ in entries] == ["v1.100", "v1.99"]
    text = render(entries)
    assert text.index("## v1.100") < text.index("## v1.99")


def test_wrapped_titles_still_parse(tmp_path):
    plan = tmp_path / "PLAN.md"
    plan.write_text(
        "1. **v1.100 - the milestone with a long\n"
        "     wrapped title** ✅ (delivered): body here\n",
        encoding="utf-8")
    entries = parse_plan(plan)
    assert entries == [("v1.100",
                        "the milestone with a long wrapped title",
                        "body here")]
