"""v5945: the README sells what the doors do — a presence guard.

The GitHub page is the product's front door: a capability that
ships without a row is a capability half-shipped, and a row that
drifts from the door's actual flags is worse than none. This pin
is a parity floor: every door the annotation-chain family added
this night (chain stamping, `verify --annotations`, the prune
call, the snapshot signature, the diary's triage lines, and the
prompt-revision cache invalidation) must be NAMED in the README
or RECALL.md with its real flag spelling — greppable, so a doc
edit that drops a promise fails the suite, not a reader's trust.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def _norm(text: str) -> str:
    # a promise can wrap across the markdown table's line breaks;
    # the parity check reads the joined prose
    return re.sub(r"\s+", " ", text)


def test_the_readme_names_the_annotation_chain():
    readme = _norm(_read("README.md"))
    for promise in (
            "verify --annotations",
            "--verdict confirmed",
            "breaks every later link",
    ):
        assert promise in readme, \
            f"README dropped the promise: {promise!r}"


def test_the_readme_names_the_related_verdict_signal():
    readme = _norm(_read("README.md"))
    for promise in (
            "SAME triage verdict",
            "--agent NAME",
    ):
        assert promise in readme, \
            f"README dropped the promise: {promise!r}"
    guide = _read("docs/RECALL.md")
    assert "`same verdict` reason" in _norm(guide), \
        "RECALL.md dropped the related-verdict promise"


def test_the_readme_names_the_snapshot_signature():
    readme = _norm(_read("README.md"))
    for promise in (
            "--key-file",
            "only the keyed signature notices",
            "restore SNAP.zip --check --key-file",
    ):
        assert promise in readme, \
            f"README dropped the promise: {promise!r}"


def test_the_readme_names_the_judge_parity_and_diary():
    readme = _norm(_read("README.md"))
    for promise in (
            "invalidates the old words' verdicts",
            "· triage: confirmed",
            "--prune 14 --dry-run",
    ):
        assert promise in readme, \
            f"README dropped the promise: {promise!r}"


def test_recall_doc_carries_the_triage_section():
    guide = _norm(_read("docs/RECALL.md"))
    for promise in (
            "## Triage annotations",
            "verify --annotations",
            "## Triage",
            "unverifiable",
            "broken evidence fleet-wide",
    ):
        assert promise in guide, \
            f"RECALL.md dropped the promise: {promise!r}"


def test_the_readme_names_the_fleet_chain_verdict():
    readme = _norm(_read("README.md"))
    for promise in (
            "TRIAGE CHAIN BROKEN xN",
            "screams only when broken",
    ):
        assert promise in readme, \
            f"README dropped the promise: {promise!r}"


def test_the_promised_flags_actually_exist():
    # the parity floor cuts both ways: a doc cannot promise a flag
    # the door never grew
    readme = _read("README.md")
    flags = set(re.findall(r"--(?:key-file|annotations|prune|query)",
                           readme))

    import approximately.cli as cli
    from approximately.cli import build_parser  # noqa: F401

    parser = cli.build_parser()
    registered = set()
    for action in parser._actions:
        registered.update(action.option_strings)
        for sub in (action.choices or {}).values():
            for a in getattr(sub, "_actions", []):
                registered.update(a.option_strings)
    missing = {f for f in flags if f not in registered}
    assert not missing, \
        f"README promises flags the parser does not know: {missing}"
