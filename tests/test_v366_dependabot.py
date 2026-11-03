"""v366: dependabot does not fight the sha-pin posture.

The supply-chain posture pins every external action by commit sha
(v3.67.1); a dependabot version bump of a pinned action would
fail the posture test — a PR that can never be green. The
dependabot config ignores `actions/*` bumps (the pins are
upgraded deliberately, by sha); the pip ecosystem stays weekly.
The config itself is pinned by this test so the ignore list
cannot silently rot.
"""

from pathlib import Path


def test_actions_bumps_are_ignored_pip_stays():
    # parsed by text, not yaml: the test env stays zero-dependency
    cfg = (Path(__file__).resolve().parents[1]
           / ".github" / "dependabot.yml").read_text(
        encoding="utf-8")
    assert 'dependency-name: "actions/*"' in cfg, \
        "without the ignore, dependabot opens PRs the posture test fails"
    assert 'package-ecosystem: "pip"' in cfg, \
        "the pip ecosystem stays weekly"
    assert 'package-ecosystem: "github-actions"' in cfg, \
        "the actions ecosystem stays watched (for the unpinned few)"
