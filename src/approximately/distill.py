"""Judge distillation: turn your recorded failures into training data for a
small local judge.

Pipeline (all offline after labeling):

1. **Label** traces. Two sources:
   - rules — attribution from the rule detectors (free, deterministic); good
     for the mechanical MAST modes;
   - teacher — a strong model labels via the judge (``--teacher``).
2. **Export** chat-format JSONL (system/user/assistant) in the *local*
   preset prompt shape, so a 1–7B model fine-tuned on it answers in exactly
   the format :func:`approximately.judge.judge_trace` parses.
3. Fine-tune with your favorite trainer (LoRA on any OpenAI-compatible
   serving stack), then point ``APPROXIMATELY_JUDGE_MODEL`` at it with
   ``preset="local"``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, List, Optional

from .attributor import attribute
from .judge import PRESETS, _compact_trace, _taxonomy_block, judge_trace
from .taxonomy import OTHER
from .trace import Trace

Labeler = Callable[[Trace], Optional[str]]


def rules_labeler(min_confidence: float = 0.7) -> Labeler:
    """Label with the rule detectors; None when nothing is confident."""
    def label(trace: Trace) -> Optional[str]:
        report = attribute(trace)
        if report.failed and report.detections:
            top = report.detections[0]
            if top.confidence >= min_confidence and top.mode_id != OTHER:
                return top.mode_id
        return None
    return label


def teacher_labeler(model: str, base_url: Optional[str] = None,
                    api_key: Optional[str] = None,
                    min_confidence: float = 0.6) -> Labeler:
    """Label with a strong judge model; None when it is unsure or fails."""
    def label(trace: Trace) -> Optional[str]:
        try:
            verdict = judge_trace(trace, model=model, base_url=base_url,
                                  api_key=api_key)
        except Exception:  # noqa: BLE001 - a bad teacher call is just a skip
            return None
        det = verdict.detection
        if det.mode_id != OTHER and det.confidence >= min_confidence:
            return det.mode_id
        return None
    return label


def example_for(trace: Trace, mode_id: str) -> dict:
    """One SFT chat example in the local-preset shape."""
    step_index = 0
    report = attribute(trace)
    if report.detections:
        step_index = report.detections[0].step_index
    assistant_payload = json.dumps(
        {"mode_id": mode_id, "step_index": step_index, "confidence": 0.9}
    )
    return {
        "messages": [
            {"role": "system",
             "content": PRESETS["local"].replace(
                 "{modes}", _taxonomy_block(compact=True))},
            {"role": "user",
             "content": json.dumps(_compact_trace(trace), default=str)},
            {"role": "assistant", "content": assistant_payload},
        ]
    }


def export_sft(traces: Iterable[Trace], out_path: Path,
               labeler: Labeler) -> dict:
    """Write JSONL training data; returns stats (labeled/skipped per mode)."""
    stats: dict = {"labeled": 0, "skipped": 0, "modes": {}}
    with open(out_path, "w", encoding="utf-8") as fh:
        for trace in traces:
            mode_id = labeler(trace)
            if mode_id is None:
                stats["skipped"] += 1
                continue
            fh.write(json.dumps(example_for(trace, mode_id), default=str) + "\n")
            stats["labeled"] += 1
            stats["modes"][mode_id] = stats["modes"].get(mode_id, 0) + 1
    return stats


@dataclass
class BenchmarkResult:
    accuracy: float
    macro_f1: float
    per_mode: dict  # mode_id -> {tp, fp, fn, precision, recall, f1}

    def summary(self) -> str:
        lines = [
            f"attribution benchmark: accuracy {self.accuracy:.2f}, "
            f"macro-F1 {self.macro_f1:.2f}"
        ]
        for mode_id, m in sorted(self.per_mode.items()):
            lines.append(
                f"  {mode_id:<7} P {m['precision']:.2f} "
                f"R {m['recall']:.2f} F1 {m['f1']:.2f} "
                f"(tp {m['tp']} fp {m['fp']} fn {m['fn']})"
            )
        return "\n".join(lines)


def _prf(tp: int, fp: int, fn: int) -> dict:
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"tp": tp, "fp": fp, "fn": fn,
            "precision": precision, "recall": recall, "f1": f1}


def evaluate(labeled: List[tuple], labeler: Labeler) -> BenchmarkResult:
    """``labeled``: list of ``(trace, gold_mode_id)`` pairs."""
    per_mode: dict = {}
    correct = 0
    for trace, gold in labeled:
        pred = labeler(trace) or OTHER
        if pred == gold:
            correct += 1
        for mode_id in {gold, pred}:
            per_mode.setdefault(mode_id, {"tp": 0, "fp": 0, "fn": 0})
        if pred == gold:
            per_mode[gold]["tp"] += 1
        else:
            per_mode[pred]["fp"] += 1
            per_mode[gold]["fn"] += 1
    for mode_id, counts in per_mode.items():
        per_mode[mode_id].update(_prf(**counts))
    macro_f1 = (
        sum(m["f1"] for m in per_mode.values()) / len(per_mode) if per_mode else 0.0
    )
    return BenchmarkResult(
        accuracy=correct / len(labeled) if labeled else 0.0,
        macro_f1=macro_f1,
        per_mode=per_mode,
    )


def load_dataset(path: Path, fmt: str = "approx") -> List[tuple]:
    """Load labeled traces.

    ``approx`` format: JSONL of ``{"task": str, "steps": [Step dicts],
    "label": "FM-x.y", "success": false, ...}`` — i.e. a Trace dict plus a
    gold ``label`` field (exactly what ``approximately export-dataset``
    writes from MAST-Data-style sources).

    ``mast`` format: JSONL with a nested ``trace``/``messages`` object and a
    label field (``label``/``failure_mode``/``mode``); mapped heuristically —
    user messages become plan steps, function/tool calls become tool steps.
    """
    labeled: List[tuple] = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            label = (record.get("label") or record.get("failure_mode")
                     or record.get("mode"))
            if fmt == "mast":
                trace = _from_mast_record(record)
            else:
                trace = Trace.from_dict(record)
            if label:
                labeled.append((trace, label))
    return labeled


def _from_mast_record(record: dict) -> Trace:
    source = record.get("trace") or record.get("messages") or record
    from .trace import Step

    trace = Trace(task=str(record.get("task", "mast record")), success=False)
    for i, msg in enumerate(source if isinstance(source, list) else []):
        role = str(msg.get("role", msg.get("type", ""))).lower()
        content = str(msg.get("content", ""))
        if role in ("user", "system"):
            trace.add(Step(kind="plan", thought=content[:200]))
        else:  # assistant/function/tool/observation -> heuristic tool step
            name = msg.get("name") or msg.get("tool") or f"msg-{i}"
            trace.add(Step(kind="tool_call", tool=str(name), args={},
                           result=content[:200]))
    return trace


def export_dataset(traces: Iterable[Trace], out_path: Path,
                   labeler: Labeler) -> dict:
    """Write labeled traces in the ``approx`` benchmark format."""
    stats = {"written": 0, "skipped": 0}
    with open(out_path, "w", encoding="utf-8") as fh:
        for trace in traces:
            mode_id = labeler(trace)
            if mode_id is None:
                stats["skipped"] += 1
                continue
            record = trace.to_dict()
            record["label"] = mode_id
            fh.write(json.dumps(record, default=str) + "\n")
            stats["written"] += 1
    return stats
