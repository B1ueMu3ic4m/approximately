"""v313: the repo's public face is code, not prose.

``meta.ABOUT`` is the GitHub About line and ``meta.TOPICS`` the topic
list; both are pinned so the repo description cannot drift from the
shipped surface: the one-liner must fit GitHub's 350-character
budget, quote the real MCP tool count, and the topics must obey
GitHub's topic grammar (lowercase/hyphen, max 20). The README banner
must quote the same tool count, so all three faces tell one story.
"""

import re
from pathlib import Path

from approximately import meta

_ROOT = Path(__file__).resolve().parents[1]


def test_about_fits_github_budget():
    assert 0 < len(meta.ABOUT) <= 350
    assert "\n" not in meta.ABOUT
    assert meta.ABOUT.strip() == meta.ABOUT


def test_about_quotes_the_real_tool_count():
    from approximately.mcp_server import _TOOLS

    claim = meta.tool_count_claim()
    assert claim is not None, "ABOUT should quote the MCP tool surface"
    assert claim == len(_TOOLS)


def test_about_names_the_findable_nouns():
    # the terms the repo must stay findable by cannot be edited away
    for term in ("flight recorder", "MAST", "replay",
                 "zero dependencies", "Python 3.10"):
        assert term.lower() in meta.ABOUT.lower(), term


def test_topics_obey_github_grammar():
    topic_re = re.compile(r"^[a-z0-9-]+$")
    assert 1 <= len(meta.TOPICS) <= 20  # GitHub caps topics at 20
    assert len(set(meta.TOPICS)) == len(meta.TOPICS)
    for t in meta.TOPICS:
        assert topic_re.fullmatch(t), t


def test_pyproject_description_stays_consistent():
    text = (_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    m = re.search(r'^description = "(.+)"$', text, re.M)
    assert m, "pyproject description missing"
    for term in ("flight recorder", "MAST"):
        assert term.lower() in m.group(1).lower(), term


def test_readme_banner_quotes_the_same_tool_count():
    claim = meta.tool_count_claim()
    assert claim is not None
    readme = (_ROOT / "README.md").read_text(encoding="utf-8")
    assert f"{claim} MCP tools" in readme
