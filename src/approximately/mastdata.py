"""MAST-Data converter: annotated trajectories -> labeled benchmark JSONL.

The MAST project (arXiv:2503.13657) published 7500+ annotated agent
trajectories (`github.com/multi-agent-systems-failure-taxonomy/MAST`).
Each file carries a human annotation block (``note.options``): a
yes/no verdict per MAST behaviour ("Step repetition",
"Derailing from task objectives", ...).

``convert_mast`` turns those files into the ``approx`` benchmark
format (`task`/`steps`/`success`/`label` JSONL) so
``approximately benchmark`` can measure the rule detectors against
human labels. Honesty rules, in order:

- Only behaviours with a matching detector are converted; the mapping
  table below is the full, citable list. Behaviours without a detector
  (invented content, discontinued reasoning, ...) never silently map
  to something adjacent.
- Only traces with **exactly one** labelled detector-covered mode
  become benchmark records: ``evaluate`` is single-label, and feeding
  it multi-label golds would manufacture precision numbers.
- Traces without annotations are skipped and counted.

The result is a smaller, honest benchmark: the counts of everything
excluded are returned and printed, never hidden.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterator, List, Optional

from .trace import Step, Trace

# MAST annotation option (exact strings from the dataset) -> FM id of
# the detector that targets that behaviour.
OPTION_TO_MODE: Dict[str, str] = {
    "Step repetition": "FM-1.3",
    "Unaware of stopping conditions": "FM-1.5",
    "Blurring roles": "FM-1.2",
    "Blurring role": "FM-1.2",
    "Trajectory restart": "FM-2.1",
    "Fail to detect ambiguities/contradictions": "FM-2.2",
    "Fail to elicit clarification": "FM-2.2",
    "Derailing from task objectives": "FM-2.3",
    "Withholding relevant information": "FM-2.4",
    "Ignoring good suggestions from other agent": "FM-2.5",
    "Misalignment between internal thoughts and response message":
        "FM-2.6",
    "Claiming that a task is done while it is not true.": "FM-3.1",
    "No attempt to verify outcome": "FM-3.2",
}


MIN_AGENT_TURNS = 2  # below this, no prose detector may fire
# (the minimum shape any prose detector needs: an
# insufficiency turn plus the eventual answer — the
# ProseAmbiguityDetector pattern)

# AG2 math-proxy harness templates: interrogator boilerplate, not
# agent behaviour. Filtered before prose analysis.
HARNESS_PREFIXES = (
    "let's use python to solve a math problem",
    "continue. please keep solving the problem",
)


@dataclass
class ConvertStats:
    converted: int = 0
    excluded_multi_label: int = 0
    excluded_no_covered_label: int = 0
    excluded_no_annotation: int = 0
    excluded_unreadable: int = 0
    excluded_no_signal: int = 0
    labels: Dict[str, int] = field(default_factory=dict)

    def summary(self) -> str:
        return (f"converted {self.converted} · "
                f"excluded: {self.excluded_multi_label} multi-label, "
                f"{self.excluded_no_covered_label} no covered mode, "
                f"{self.excluded_no_annotation} unannotated, "
                f"{self.excluded_no_signal} too few agent turns, "
                f"{self.excluded_unreadable} unreadable")


def _iter_files(source: Path) -> Iterator[Path]:
    for path in sorted(Path(source).rglob("*.json")):
        yield path


def _gold_modes(record: dict) -> List[str]:
    note = record.get("note")
    options = (note.get("options") if isinstance(note, dict) else None) or {}
    modes = []
    for option, verdict in options.items():
        if str(verdict).strip().lower() == "yes" and option in OPTION_TO_MODE:
            mode_id = OPTION_TO_MODE[option]
            if mode_id not in modes:
                modes.append(mode_id)
    return modes


_RESPONSE_MARKER = __import__("re").compile(
    r"^([\w-]*)'s Response:\s?(.*)$")


def _hyperagent_turns(trajectory: list) -> List[tuple]:
    """Parse HyperAgent log-line trajectories into (role, text) turns.

    HyperAgent dumps its run as log lines (``<logger> - INFO - msg``);
    agent turns start at "…'s Response:" markers and accumulate lines
    until the next marker. Everything else (init lines, raw code
    echoes) belongs to the open turn or is dropped before it starts.
    """
    turns: List[tuple] = []
    role: Optional[str] = None
    buffer: List[str] = []
    for line in trajectory:
        if not isinstance(line, str) or not line.strip():
            continue
        parts = line.split(" - ", 2)
        msg = parts[2] if len(parts) == 3 else parts[-1]
        m = _RESPONSE_MARKER.match(msg)
        if m:
            if role and buffer:
                turns.append((role, " ".join(buffer)))
            role = m.group(1)
            buffer = [m.group(2)] if m.group(2) else []
        elif role is not None:
            buffer.append(msg)
    return _flush(turns, role, buffer)


def _flush(turns: List[tuple], role: Optional[str],
           buffer: List[str]) -> List[tuple]:
    if role and buffer:
        turns.append((role, " ".join(buffer)))
    return turns


def _flatten(content: object) -> str:
    text = " ".join(str(p) for p in content) \
        if isinstance(content, list) else str(content or "")
    return text.strip()


def _step_for(role: str, name: str, text: str) -> Step:
    if role in ("user", "system"):
        return Step(kind="plan", thought=text[:400])
    return Step(kind="tool_call", tool=name, args={}, result=text[:400])


def _task_of(record: dict) -> str:
    parts = record.get("problem_statement") or ["(no statement)"]
    return " ".join(str(p) for p in parts)[:400]


def _success_of(record: dict):
    other = record.get("other_data") or {}
    return bool(other.get("correct")) if "correct" in other else None


def _to_trace(record: dict) -> Trace:
    trace = Trace(task=_task_of(record), success=_success_of(record))
    trace.meta["prose"] = True  # activates the prose detector family
    trajectory = record.get("trajectory") or []
    if trajectory and isinstance(trajectory[0], str):
        # HyperAgent log-line schema
        for role, text in _hyperagent_turns(trajectory):
            trace.add(Step(kind="tool_call", tool=role.lower(), args={},
                           result=text[:2000]))
        return trace
    for i, msg in enumerate(trajectory):
        if not isinstance(msg, dict):
            continue
        text = _flatten(msg.get("content"))
        if not text:
            continue
        role = str(msg.get("role", "")).lower()
        name = str(msg.get("name") or msg.get("tool") or f"msg-{i}")
        trace.add(_step_for(role, name, text))
    return trace


def _signal_turns(trace: Trace) -> int:
    """Agent turns with content, minus harness boilerplate."""
    return sum(1 for st in trace.steps
               if st.kind == "tool_call" and st.result
               and not st.result.lower().startswith(HARNESS_PREFIXES))


def convert_mast(source: Path, out_path: Path) -> ConvertStats:
    """Convert a MAST-Data checkout into labeled ``approx`` JSONL."""
    stats = ConvertStats()
    with open(out_path, "w", encoding="utf-8") as fh:
        for path in _iter_files(source):
            try:
                with open(path, encoding="utf-8") as fh_in:
                    record = json.load(fh_in)
                if not isinstance(record, dict):
                    raise ValueError("not an object")
            except (OSError, json.JSONDecodeError, ValueError):
                stats.excluded_unreadable += 1
                continue

            note = record.get("note")
            if not isinstance(note, dict) or not note.get("options"):
                stats.excluded_no_annotation += 1
                continue

            modes = _gold_modes(record)
            if len(modes) == 0:
                stats.excluded_no_covered_label += 1
                continue
            if len(modes) > 1:
                stats.excluded_multi_label += 1
                continue

            trace = _to_trace(record)
            if modes:
                # a yes-annotated MAST behaviour asserts the run
                # contained a failure; task-level correctness (was the
                # issue eventually fixed?) is a different question and
                # must not mask it from attribution
                trace.success = False
                trace.meta["task_correct"] = _success_of(record)
            if _signal_turns(trace) < MIN_AGENT_TURNS:
                stats.excluded_no_signal += 1
                continue
            payload = trace.to_dict()
            payload["label"] = modes[0]
            fh.write(json.dumps(payload, default=str) + "\n")
            stats.converted += 1
            stats.labels[modes[0]] = stats.labels.get(modes[0], 0) + 1
    return stats
