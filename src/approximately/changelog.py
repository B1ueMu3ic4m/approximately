"""Generate CHANGELOG.md from the PLAN milestone ledger.

docs/PLAN.md is the single source of truth: every delivered round is
a numbered item whose heading carries the version ("**v1.53 - MCP
tool #30 ...** ✅ (delivered): ..."). This module turns that ledger
into a standard changelog, newest first, one section per version —
so the changelog cannot drift from the plan it summarizes.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional, Tuple

_HEADING = re.compile(
    r"^(\d+)\. \*\*(v\d+(?:\.\d+)*) [-\u2013\u2014] (.+?)\*\*"
    r"(?: \u2705[^:]*)?(?:[:]\s*(.*))?$")


def parse_plan(plan_path: Path) -> List[Tuple[str, str, str]]:
    """(version, title, body) per delivered item, newest first."""
    entries: List[Tuple[str, str, str]] = []
    current: Optional[Tuple[str, str, List[str]]] = None

    def close():
        nonlocal current
        if current is not None:
            entries.append(current)
            current = None

    for line in plan_path.read_text(encoding="utf-8").splitlines():
        head = _HEADING.match(line)
        if head:
            close()
            current = (head.group(2), head.group(3),
                       [head.group(4)] if head.group(4) else [])
            continue
        if current is not None:
            if line.strip():
                current[2].append(line.strip())
            elif current[2]:
                close()  # blank line after the body: item over
    close()

    def version_key(version: str) -> tuple:
        return tuple(int(part) for part in version[1:].split("."))

    entries.sort(key=lambda e: version_key(e[0]), reverse=True)
    return [(version, title, " ".join(body))
            for version, title, body in entries]


def render(entries: List[Tuple[str, str, str]]) -> str:
    # early plans shipped several items per version: one section
    # per version, bodies joined
    merged: List[Tuple[str, str, List[str]]] = []
    for version, title, body in entries:
        if merged and merged[-1][0] == version:
            merged[-1][2].append(f"{title.rstrip('.')}.")
            merged[-1][2].append(body)
        else:
            merged.append((version, title, [body]))
    out = ["# Changelog", "",
           "Generated from [docs/PLAN.md](docs/PLAN.md) — the single",
           "source of truth. Newest first.", ""]
    for version, _title, bodies in merged:
        out.append(f"## {version}")
        out.append("")
        for chunk in bodies:
            if chunk:
                out.append(chunk)
                out.append("")
        out[-1] = out[-1].rstrip()
        out.append("")
    return "\n".join(out)


def write_changelog(plan_path: Path, output: Path) -> int:
    entries = parse_plan(plan_path)
    output.write_text(render(entries) + "\n", encoding="utf-8")
    return len(entries)
