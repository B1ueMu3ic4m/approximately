"""Structural trace diff: git-style comparison of two agent runs.

The aligner (``align.py``) scores the alignment; this module **traces
back** the optimal path through the Needleman-Wunsch matrix and turns it
into an explicit edit script — every step of both runs classified as:

- ``equal``   same tool, same argument structure, aligned
- ``mutated`` same tool, different argument structure or result
- ``deleted`` present in A, absent from the aligned B
- ``inserted`` present in B, absent from the aligned A

The classic debugging workflow this enables: diff the failed run against
the last successful one — the first ``mutated`` is where behavior broke.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Tuple

from .align import (
    GAP_PENALTY,
    MATCH_SCORE,
    STRUCTURE_SUBSTITUTION,
    normalize_step,
)
from .trace import TOOL_CALL, Trace


class Op(Enum):
    EQUAL = "="
    MUTATED = "~"
    DELETED = "-"
    INSERTED = "+"


@dataclass
class DiffEntry:
    op: Op
    a_index: int | None  # step index in trace A (None for inserts)
    b_index: int | None  # step index in trace B (None for deletions)
    a_tool: str | None
    b_tool: str | None
    detail: str = ""

    @property
    def symbol(self) -> str:
        return self.op.value

    def render(self) -> str:
        if self.op == Op.DELETED:
            return f"- #{self.a_index} {self.a_tool}: {self.detail}"
        if self.op == Op.INSERTED:
            return f"+ #{self.b_index} {self.b_tool}: {self.detail}"
        head = f"#{self.a_index} -> #{self.b_index}"
        if self.op == Op.MUTATED:
            return f"~ {head} {self.a_tool}: {self.detail}"
        return f"= {head} {self.a_tool}: {self.detail}"


@dataclass
class TraceDiff:
    a_id: str
    b_id: str
    entries: List[DiffEntry] = field(default_factory=list)
    similarity: float = 0.0

    @property
    def counts(self) -> dict:
        counts = dict.fromkeys(Op, 0)
        for entry in self.entries:
            counts[entry.op] += 1
        return counts

    def summary(self) -> str:
        c = self.counts
        lines = [(f"diff {self.a_id} vs {self.b_id} - similarity "
                  f"{self.similarity:.0%}")]
        lines.append(
            f"  = {c[Op.EQUAL]} equal · ~ {c[Op.MUTATED]} mutated · "
            f"- {c[Op.DELETED]} deleted · + {c[Op.INSERTED]} inserted"
        )
        lines.extend(
            f"  {entry.render()}" for entry in self.entries
            if entry.op != Op.EQUAL)
        return "\n".join(lines)


def _substitution(ida: str, idb: str, sta: str, stb: str) -> Tuple[float, Op]:
    if ida == idb:
        return MATCH_SCORE, Op.EQUAL
    if sta == stb:
        return STRUCTURE_SUBSTITUTION, Op.MUTATED
    return 0.0, Op.MUTATED


def _dp_matrix(toks_a, toks_b):
    """Forward Needleman-Wunsch matrix (same scoring as align.align_score)."""
    n, m = len(toks_a), len(toks_b)
    dp = [[0.0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        dp[i][0] = dp[i - 1][0] + GAP_PENALTY
    for j in range(1, m + 1):
        dp[0][j] = dp[0][j - 1] + GAP_PENALTY
    for i in range(1, n + 1):
        ida, sta = toks_a[i - 1]
        for j in range(1, m + 1):
            idb, stb = toks_b[j - 1]
            sub, _ = _substitution(ida, idb, sta, stb)
            dp[i][j] = max(dp[i - 1][j - 1] + sub,
                           dp[i - 1][j] + GAP_PENALTY,
                           dp[i][j - 1] + GAP_PENALTY)
    return dp


def _traceback(dp, toks_a, toks_b, steps_a, steps_b) -> List[DiffEntry]:
    """Walk the optimal path: diagonal, then delete, then insert."""
    entries: List[DiffEntry] = []
    i, j = len(toks_a), len(toks_b)
    while i > 0 or j > 0:
        if i > 0 and j > 0:
            ida, sta = toks_a[i - 1]
            idb, stb = toks_b[j - 1]
            sub, op = _substitution(ida, idb, sta, stb)
            if dp[i][j] == dp[i - 1][j - 1] + sub:
                sa = steps_a[i - 1]
                sb = steps_b[j - 1]
                detail = ""
                if op == Op.MUTATED:
                    detail = f"{_preview(sa.result)} vs {_preview(sb.result)}"
                entries.append(DiffEntry(
                    op, sa.index, sb.index, sa.tool, sb.tool, detail))
                i, j = i - 1, j - 1
                continue
        if i > 0 and dp[i][j] == dp[i - 1][j] + GAP_PENALTY:
            sa = steps_a[i - 1]
            entries.append(DiffEntry(Op.DELETED, sa.index, None,
                                     sa.tool, None, _preview(sa.result)))
            i -= 1
            continue
        sb = steps_b[j - 1]
        entries.append(DiffEntry(Op.INSERTED, None, sb.index, None,
                                 sb.tool, _preview(sb.result)))
        j -= 1
    entries.reverse()  # traceback walked newest-first
    return entries


def diff(a: Trace, b: Trace) -> TraceDiff:
    """Align two traces and return the full edit script."""
    steps_a = [s for s in a.steps if s.kind == TOOL_CALL]
    steps_b = [s for s in b.steps if s.kind == TOOL_CALL]
    toks_a = [normalize_step(s) for s in steps_a]
    toks_b = [normalize_step(s) for s in steps_b]

    dp = _dp_matrix(toks_a, toks_b)
    entries = _traceback(dp, toks_a, toks_b, steps_a, steps_b)

    score = dp[-1][-1]
    best = MATCH_SCORE * max(len(toks_a), len(toks_b)) if max(len(toks_a),
                                                              len(toks_b)) \
        else 1.0
    similarity = max(0.0, min(1.0, score / best))
    return TraceDiff(a_id=a.id, b_id=b.id, entries=entries,
                     similarity=similarity)


def _preview(text: str, limit: int = 40) -> str:
    text = " ".join((text or "").split())
    return text[:limit] + ("..." if len(text) > limit else "")
