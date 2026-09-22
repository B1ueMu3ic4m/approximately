"""Plain-language deep dives for each MAST failure mode.

``approximately explain FM-1.3`` answers "what does this mean for my
agent?": the taxonomy definition, the published share, the mechanical
detectors that watch for the mode, and the engineering fixes — including
the ones the MAST paper measured. The detector column is derived from
the live registries (every detector class carries its ``mode_id``), so
a new detector appears here without touching this module.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

from .detectors import ALL_DETECTORS
from .taxonomy import FAILURE_MODES, all_modes


def detectors_for_mode(mode_id: str) -> List[Tuple[str, str]]:
    """``(family, class name)`` pairs watching ``mode_id``.

    Family is ``"tool"`` for detectors over real tool-call traces and
    ``"prose"`` for detectors over assistant-turn traces (MAST-Data
    style). The prose registry imports lazily, matching
    :func:`approximately.detectors.run_rules`.
    """
    from .prose import PROSE_DETECTORS

    tool = [(d.mode_id, type(d).__name__) for d in ALL_DETECTORS]
    prose = [(d.mode_id, type(d).__name__) for d in PROSE_DETECTORS]
    return ([("tool", name) for mid, name in tool if mid == mode_id]
            + [("prose", name) for mid, name in prose if mid == mode_id])


def _watched_by(mode_id: str) -> str:
    groups: Dict[str, List[str]] = {}
    for family, name in detectors_for_mode(mode_id):
        groups.setdefault(family, []).append(name)
    if not groups:
        return ("no mechanical detector — attributed by the LLM judge "
                "or manual review")
    return "; ".join(f"{family}: {', '.join(names)}"
                     for family, names in groups.items())


def explain_text(mode_id: str) -> str:
    """Full deep dive for one failure mode. KeyError on unknown ids."""
    mode = FAILURE_MODES[mode_id]  # KeyError propagates: CLI maps to exit 1
    lines = [f"{mode.label}  [{mode.category} · {mode.category_name}]",
             "", mode.definition, ""]
    if mode.mast_share is not None:
        lines.append(f"Published share: {mode.mast_share:.2f}% of MAST "
                     "traces show this mode.")
        lines.append("")
    lines.append(f"Watched by: {_watched_by(mode_id)}")
    lines.append("")
    lines.append("Fixes:")
    for i, fix in enumerate(mode.fixes, 1):
        lines.append(f"  {i}. {fix}")
    return "\n".join(lines)


def explain_overview() -> str:
    """One row per mode: id, name, share, detector coverage counts."""
    lines = [("MAST failure modes — 'approximately explain <ID>' for the "
              "full deep dive"), "",
             f"{'ID':<8} {'mode':<38} {'share':>6}  tool prose",]
    for mode in all_modes():
        share = f"{mode.mast_share:.1f}%" if mode.mast_share is not None \
            else "—"
        tool_n = sum(1 for f, _ in detectors_for_mode(mode.id)
                     if f == "tool")
        prose_n = sum(1 for f, _ in detectors_for_mode(mode.id)
                      if f == "prose")
        lines.append(f"{mode.id:<8} {mode.name:<38} {share:>6}  "
                     f"{tool_n:>4} {prose_n:>5}")
    lines.append("")
    lines.append("tool = real tool-call traces; prose = assistant-turn "
                 "traces (MAST-Data style).")
    return "\n".join(lines)
