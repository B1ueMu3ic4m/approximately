"""Generate CHANGELOG.md from the PLAN milestone ledger.

docs/PLAN.md is the single source of truth: every delivered round is
a numbered item whose heading carries the version ("**v1.53 - MCP
tool #30 ...** ✅ (delivered): ..."). This module turns that ledger
into a standard changelog, newest first, one section per version —
so the changelog cannot drift from the plan it summarizes.

Item headings may wrap across lines (long titles do), so the parser
scans the full text: an item runs from its `N. **vX.Y - title**`
opener to the next opener or end of file. Titles may not contain
nested `**` (the round-9 rule) — which also keeps deferred lines
like `**deferred with reasons**` from masquerading as closings;
deferred/queued items are additionally excluded by content.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import List, Tuple

_ITEM = re.compile(
    r"^\d+\. \*\*(v\d+(?:\.\d+)*) [-\u2013\u2014] "
    r"((?:[^*]|\*(?!\*))+?)\*\*"
    r"(?P<rest>.*?)"
    r"(?=^\d+\. \*\*v\d|\Z)",
    re.M | re.S)

_DELIVERED = re.compile(r"^\u2705[^:]*:\s*")


def parse_plan(plan_path: Path) -> List[Tuple[str, str, str]]:
    """(version, title, body) per delivered item, newest first.

    Titles unwrap (newlines collapse to spaces). Deferred and queued
    items are excluded by content, not by punctuation luck.
    """
    entries: List[Tuple[str, str, str]] = []
    for match in _ITEM.finditer(
            plan_path.read_text(encoding="utf-8")):
        if match.group(1) is None:
            continue  # the trailing \Z alternative: no item here
        version = match.group(1)
        title = " ".join(match.group(2).split())
        rest = " ".join(match.group("rest").split())
        if re.search(r"\bdeferred\b|\bqueued\b", rest, re.I):
            continue
        body = _DELIVERED.sub("", rest).strip()
        entries.append((version, title, body))

    def version_key(version: str) -> tuple:
        return tuple(int(part) for part in version[1:].split("."))

    entries.sort(key=lambda e: version_key(e[0]), reverse=True)
    return entries


def render(entries: List[Tuple[str, str, str]]) -> str:
    # early plans shipped several items per version: one section
    # per version, bullets joined
    merged: List[Tuple[str, List[str]]] = []
    for version, title, body in entries:
        bullet = f"- {title.rstrip('.')}."
        if body:
            bullet += f" {body}"
        if merged and merged[-1][0] == version:
            merged[-1][1].append(bullet)
        else:
            merged.append((version, [bullet]))
    out = ["# Changelog", "",
           "Generated from [docs/PLAN.md](docs/PLAN.md) — the single",
           "source of truth. Newest first.", ""]
    for version, bullets in merged:
        out.append(f"## {version}")
        out.append("")
        out.extend(bullets)
        out.append("")
    return "\n".join(out)


def write_changelog(plan_path: Path, output: Path) -> int:
    entries = parse_plan(plan_path)
    output.write_text(render(entries) + "\n", encoding="utf-8")
    return len(entries)
