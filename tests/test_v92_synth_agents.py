"""v92: the synthetic corpus carries agent identity.

Every record is stamped agent=hyperagent so CI fixtures exercise
the Step.agent paths (scorecard, reports, digest snapshots) on
every bench run. Labels and floors are untouched: attribution is
mode-level, and no synth scenario carries the share_with/role
meta the identity-reading detectors key on.
"""

import json
from pathlib import Path

from approximately.cluster import agent_scorecard
from approximately.distill import load_dataset

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "docs" / "mast-bench-synth.jsonl"


def _records():
    return [json.loads(line) for line in
            CORPUS.read_text(encoding="utf-8").splitlines() if line]


def test_every_step_carries_agent():
    records = _records()
    assert len(records) == 180
    for rec in records:
        for step in rec["steps"]:
            assert step.get("agent") == "hyperagent", rec["id"]


def test_agent_field_does_not_change_labels():
    # load_dataset drops records with empty labels; the count and
    # label set are the contract the floors were measured on
    labeled = load_dataset(CORPUS, fmt="jsonl")
    assert len(labeled) == 150
    modes = {m for _, labels in labeled for m in
             (labels if isinstance(labels, list) else [labels])}
    assert modes == {"FM-1.3", "FM-2.1", "FM-2.6", "FM-3.2"}


def test_scorecard_sees_the_stamped_agent():
    labeled = load_dataset(CORPUS, fmt="jsonl")
    rows = agent_scorecard([t for t, _ in labeled[:10]])
    assert [r["agent"] for r in rows] == ["hyperagent"]
