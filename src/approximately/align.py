"""Trajectory sequence alignment: Needleman-Wunsch over normalized actions.

Two agent runs rarely take *identical* paths, but similar runs share the
same *shape*: the same tools in the same order with roughly the same
argument structure. This module borrows the classic bioinformatics answer
to that problem — Needleman-Wunsch global alignment with a substitution
matrix — and applies it to normalized action sequences.

Each step normalizes to a token:

- ``kind:tool`` when the two steps share the tool (match, score +2)
- ``kind:tool~`` when the tool matches but the argument *structure*
  differs (silent substitution, score +1)
- everything else mismatches (score 0); gaps score -1

Similarity is the alignment score normalized by the maximum possible score,
so it lands in [0, 1] and is comparable across trace pairs of any length.
"""

from __future__ import annotations

import json
from typing import List, Tuple

from .trace import TOOL_CALL, Trace

GAP_PENALTY = -1.0
MATCH_SCORE = 2.0
STRUCTURE_SUBSTITUTION = 1.0


def normalize_step(step) -> Tuple[str, str]:
    """A step becomes (identity_token, structure_token).

    ``identity_token`` is the full ``kind:tool:sorted-arg-keys:sorted-arg-
    values`` signature; ``structure_token`` is ``kind:tool`` plus the sorted
    argument *keys* — two calls to the same tool with the same argument
    shape align even when the values differ (different flights, same
    booking shape).
    """
    head = f"{step.kind}:{step.tool or '-'}"
    if step.kind != TOOL_CALL:
        text = (step.thought or step.result or "").strip().lower()
        return head, f"{head}:{text[:40]}"
    try:
        args = step.args if isinstance(step.args, dict) else {}
        keys = ",".join(sorted(args.keys()))
        values = ",".join(
            f"{k}={json.dumps(args[k], sort_keys=True, default=str)}"
            for k in sorted(args.keys())
        )
    except (TypeError, ValueError):  # pragma: no cover - defensive
        keys, values = "?", "?"
    return f"{head}:{values}", f"{head} {{{keys}}}"


def tokens(trace: Trace) -> List[Tuple[str, str]]:
    """Identity/structure token pairs for every tool-call step of a trace."""
    return [normalize_step(s) for s in trace.steps if s.kind == TOOL_CALL]


def align_score(a: List[Tuple[str, str]], b: List[Tuple[str, str]]) -> float:
    """Needleman-Wunsch global alignment score of two token sequences."""
    n, m = len(a), len(b)
    if n == 0 and m == 0:
        return 0.0
    # dp[i][j]: best score aligning a[:i] with b[:j]
    dp = [[0.0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        dp[i][0] = dp[i - 1][0] + GAP_PENALTY
    for j in range(1, m + 1):
        dp[0][j] = dp[0][j - 1] + GAP_PENALTY
    for i in range(1, n + 1):
        ida, sta = a[i - 1]
        for j in range(1, m + 1):
            idb, stb = b[j - 1]
            sub = MATCH_SCORE if ida == idb else (
                STRUCTURE_SUBSTITUTION if sta == stb else 0.0)
            dp[i][j] = max(
                dp[i - 1][j - 1] + sub,   # align / substitute
                dp[i - 1][j] + GAP_PENALTY,  # gap in b
                dp[i][j - 1] + GAP_PENALTY,  # gap in a
            )
    return dp[n][m]


def similarity(a: Trace, b: Trace) -> float:
    """Normalized alignment similarity of two traces, in [0, 1]."""
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return 0.0
    score = align_score(ta, tb)
    best = MATCH_SCORE * max(len(ta), len(tb))
    return max(0.0, min(1.0, score / best))


def rank_similar(target: Trace, traces: List[Trace],
                 top: int = 5) -> List[Tuple[Trace, float]]:
    """The ``top`` most alignment-similar traces to *target*, best first.

    Two savings keep this linear-ish on big stores while returning
    exactly the same ranking as the brute-force scan:

    - the target's tokens are normalized once, not once per candidate
    - a candidate whose length-ratio upper bound
      (``similarity <= 2*min/max``) is strictly below the current
      Nth-best score can no longer enter the top N, so its quadratic
      DP is skipped. Input order is preserved, so ties break exactly
      as they did before.
    """
    target_tokens = tokens(target)
    n_target = len(target_tokens)
    scored: List[Tuple[Trace, float]] = []
    threshold = 0.0  # score of the current Nth place (0 while unfilled)
    for candidate in traces:
        if candidate.id == target.id:
            continue
        cand_tokens = tokens(candidate)
        n_cand = len(cand_tokens)
        if n_target == 0 or n_cand == 0:
            score = 0.0
        else:
            upper = min(n_target, n_cand) / max(n_target, n_cand)
            if len(scored) >= top and upper < threshold:
                continue  # cannot enter the top N
            score = max(0.0, min(
                1.0, align_score(target_tokens, cand_tokens)
                / (MATCH_SCORE * max(n_target, n_cand))))
        scored.append((candidate, score))
        scored.sort(key=lambda pair: -pair[1])
        del scored[top:]
        if top > 0 and len(scored) >= top:
            threshold = scored[-1][1]
    return scored


def similar_payload(target, traces, top: int = 5) -> dict:
    """The `similar` answer as data (shared by CLI --json and MCP)."""
    ranked = rank_similar(target, traces, top=max(0, top))
    return {"trace": target.id,
            "matches": [{"id": c.id, "task": c.task,
                         "similarity": round(score, 4)}
                        for c, score in ranked]}
