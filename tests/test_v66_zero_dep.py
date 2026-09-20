"""v0.66 — zero-dependency guard: the core imports stdlib only.

The headline claim is "zero dependencies". This test makes it
mechanical: every module-level (top-of-file) import in the core
package must come from the standard library or from approximately
itself. Optional extras (tiktoken, openai) are allowed only as
lazy imports inside function bodies — that is the documented design
("extras stay optional and lazy").
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

CORE = Path(__file__).resolve().parent.parent / "src" / "approximately"


def _module_level_third_party(path: Path) -> list:
    stdlib = set(sys.stdlib_module_names)
    tree = ast.parse(path.read_text(encoding="utf-8"))
    offenders = []

    def walk_body(body, at_module_level):
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                 ast.ClassDef, ast.Try)):
                # imports nested anywhere below these are lazy/optional
                continue
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    if root not in stdlib and root != "approximately":
                        offenders.append(f"{path.name}:{node.lineno} "
                                         f"import {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                if node.level == 0 and node.module:
                    root = node.module.split(".")[0]
                    if root not in stdlib and root != "approximately":
                        offenders.append(f"{path.name}:{node.lineno} "
                                         f"from {node.module}")
            if at_module_level and isinstance(node, (ast.If, ast.With)):
                walk_body(node.body, True)

    walk_body(tree.body, True)
    return offenders


def test_core_module_level_imports_are_stdlib_only():
    offenders = []
    for path in sorted(CORE.rglob("*.py")):
        if "contrib" in path.parts:
            continue  # adapters are optional extras by design
        offenders.extend(_module_level_third_party(path))
    assert offenders == [], (
        "top-level third-party imports break the zero-dependency "
        f"claim: {offenders}")


def test_contrib_adapters_are_excluded_from_the_guard():
    """The guard's contract: contrib/ is outside its scope (adapters
    legitimately import their frameworks at module level)."""
    adapters = list((CORE / "contrib").rglob("*.py"))
    assert adapters, "contrib adapters missing?"


def test_auditor_flags_a_real_violation(tmp_path):
    """Self-test: the auditor catches what it exists to catch."""
    bad = tmp_path / "fake_core.py"
    bad.write_text(
        "import requests\n"
        "import json\n"
        "def f():\n"
        "    import tiktoken  # lazy is fine\n",
        encoding="utf-8")
    offenders = _module_level_third_party(bad)
    assert offenders == [f"fake_core.py:1 import requests"]


def test_auditor_allows_lazy_optional_imports(tmp_path):
    good = tmp_path / "fake_core.py"
    good.write_text(
        "import json\n"
        "def f():\n"
        "    import tiktoken\n"
        "def g():\n"
        "    from openai import OpenAI\n",
        encoding="utf-8")
    assert _module_level_third_party(good) == []
