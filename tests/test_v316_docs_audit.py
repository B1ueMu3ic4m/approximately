"""v316: the docs audit — README and tutorial claims held to code.

The README's numbers are marketing until a test reads them. This
batch pins the verifiable ones: the 14 classified MAST modes (plus
the OTHER bucket) behind the "all 14 modes" claim, the 3 failure
categories, the 7 framework adapters behind the banner's count, the
tutorial's operations-night commands against the registered doors,
and ARCHITECTURE's module names against the tree. Docs rot is a
test failure now, not a slow surprise.
"""

import re
from pathlib import Path

from approximately.cli import build_parser
from approximately.taxonomy import FAILURE_MODES, OTHER

_ROOT = Path(__file__).resolve().parents[1]


def _read(*parts) -> str:
    return (_ROOT.joinpath(*parts)).read_text(encoding="utf-8")


def _registered_doors() -> set:
    parser = build_parser()
    return set(parser._subparsers._group_actions[0].choices)


def test_the_fourteen_modes_are_fourteen():
    classified = [m for m in FAILURE_MODES.values() if m.id != OTHER]
    assert len(classified) == 14
    assert len({m.category for m in classified}) == 3


def test_readme_mode_claims_match_the_taxonomy():
    readme = _read("README.md")
    assert "14 scientifically-classified failure modes" in readme
    assert "14 failure modes across 3 categories" in readme
    assert "All 14 MAST modes" in readme


def test_seven_framework_adapters_are_seven():
    contrib = (_ROOT / "src" / "approximately" / "contrib")
    adapters = [p.stem for p in contrib.glob("*.py")
                if p.stem not in ("__init__",)]
    assert len(adapters) == 7
    assert "7 framework" in _read("README.md")


def test_tutorial_commands_are_real_doors():
    tutorial = _read("docs", "TUTORIAL.md")
    chapter = tutorial.split("## 13. The on-call loop")[1]
    doors = _registered_doors()
    used = set(re.findall(r"approximately ([a-z][a-z-]*)", chapter))
    assert used, "the ops chapter lost its commands"
    ghost = used - doors
    assert not ghost, f"tutorial names doors that do not exist: {ghost}"


def test_architecture_module_names_exist():
    arch = _read("docs", "ARCHITECTURE.md")
    named = set(re.findall(r"`([a-z_]+)\.py`", arch))
    assert named, "architecture names no modules"
    src = _ROOT / "src" / "approximately"
    missing = {n for n in named if not (src / f"{n}.py").is_file()}
    assert not missing, f"architecture names dead modules: {missing}"


def test_architecture_covers_the_v3_operations_loop():
    arch = _read("docs", "ARCHITECTURE.md")
    for module in ("tail", "triage", "grade", "handoff", "redact",
                   "snapshot", "prices", "digest", "retention"):
        assert module in arch, f"architecture never names {module}"
