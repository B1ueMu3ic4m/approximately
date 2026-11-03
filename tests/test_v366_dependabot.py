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

import yaml


def test_actions_bumps_are_ignored_pip_stays():
    cfg = yaml.safe_load((Path(__file__).resolve().parents[1]
                          / ".github" / "dependabot.yml")
                         .read_text(encoding="utf-8"))
    updates = {u["package-ecosystem"]: u for u in cfg["updates"]}
    actions = updates.get("github-actions")
    assert actions is not None, "the actions ecosystem vanished"
    ignored = [i["dependency-name"]
               for i in actions.get("ignore", [])]
    assert "actions/*" in ignored, \
        "without the ignore, dependabot opens PRs the posture test fails"
    assert "pip" in updates, "the pip ecosystem stays weekly"
