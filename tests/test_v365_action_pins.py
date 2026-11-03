"""v365: the supply-chain posture is sha pins, enforced.

Every external action in the workflows is pinned to a full commit
sha — a mutable tag (``actions/checkout@v4``) can be re-pointed,
and the repo's CI is its own audit chain. The posture was adopted
workflow by workflow; this test holds the whole directory to it
(local composite actions (``uses: ./``) are not external).
"""

import re
from pathlib import Path

SHA = re.compile(r"@[0-9a-f]{40}\b")


def test_every_external_action_is_sha_pinned():
    workflows = sorted(
        (Path(__file__).resolve().parents[1]
         / ".github" / "workflows").glob("*.yml"))
    assert len(workflows) >= 5, "the workflow dir lost its files"
    offenders = []
    for wf in workflows:
        for i, line in enumerate(wf.read_text(
                encoding="utf-8").splitlines(), 1):
            m = re.search(r"uses:\s*(\S+)", line)
            if not m:
                continue
            ref = m.group(1)
            if ref.startswith("./"):
                continue  # local composite action
            if not SHA.search(ref):
                offenders.append(f"{wf.name}:{i}: {ref}")
    assert not offenders, \
        "mutable action refs found: " + "; ".join(offenders)
