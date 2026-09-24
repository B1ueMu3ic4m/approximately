"""Judge distillation: turn your recorded failures into training data for a
small local judge.

Pipeline (all offline after labeling):

1. **Label** traces. Two sources:
   - rules — attribution from the rule detectors (free, deterministic); good
     for the mechanical MAST modes;
   - teacher - a strong model labels via the judge (``--teacher``).
2. **Export** chat-format JSONL (system/user/assistant) in the *local*
   preset prompt shape, so a 1-7B model fine-tuned on it answers in exactly
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
from .detectors import run_rules
from .judge import PRESETS, _compact_trace, _taxonomy_block, judge_trace
from .taxonomy import OTHER, get_mode
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
        except Exception:
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
            (f"attribution benchmark: accuracy {self.accuracy:.2f}, "
            f"macro-F1 {self.macro_f1:.2f}")
        ]
        for mode_id, m in sorted(self.per_mode.items()):
            p_lo, p_hi = m["precision_ci"]
            r_lo, r_hi = m["recall_ci"]
            lines.append(
                f"  {mode_id:<7} P {m['precision']:.2f} "
                f"[{p_lo:.2f},{p_hi:.2f}] "
                f"R {m['recall']:.2f} [{r_lo:.2f},{r_hi:.2f}] "
                f"F1 {m['f1']:.2f} "
                f"(tp {m['tp']} fp {m['fp']} fn {m['fn']})"
            )
        return "\n".join(lines)


def wilson_interval(successes: int, n: int,
                    z: float = 1.96) -> tuple:
    """95% Wilson score interval for a binomial proportion.

    Point estimates on small samples lie; the Wilson interval
    (Wilson 1927) stays inside [0, 1] and doesn't blow up at 0 or n
    the way the naive normal approximation does. Returns
    ``(low, high)``; ``(0.0, 0.0)`` for empty samples.
    """
    if n <= 0:
        return (0.0, 0.0)
    p = successes / n
    denom = 1.0 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    spread = (z * ((p * (1.0 - p) / n
                    + z * z / (4.0 * n * n)) ** 0.5)) / denom
    return (max(0.0, center - spread), min(1.0, center + spread))


def _prf(tp: int, fp: int, fn: int) -> dict:
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    p_lo, p_hi = wilson_interval(tp, tp + fp)
    r_lo, r_hi = wilson_interval(tp, tp + fn)
    return {"tp": tp, "fp": fp, "fn": fn,
            "precision": precision, "recall": recall, "f1": f1,
            "precision_ci": (round(p_lo, 3), round(p_hi, 3)),
            "recall_ci": (round(r_lo, 3), round(r_hi, 3))}


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
        for raw in fh:
            line = raw.strip()
            if not line:
                continue
            record = json.loads(line)
            label = (record.get("labels") if record.get("labels")
                     else record.get("label") or record.get("failure_mode")
                     or record.get("mode"))
            trace = _from_mast_record(record) if fmt == "mast" else Trace.from_dict(record)
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


def _tally_modes(per_mode: dict, predicted: set, gold_set: set,
                 tp_set: set) -> None:
    for mode_id in gold_set | predicted:
        counts = per_mode.setdefault(mode_id, {"tp": 0, "fp": 0, "fn": 0})
        if mode_id in tp_set:
            counts["tp"] += 1
        elif mode_id in predicted:
            counts["fp"] += 1
        elif mode_id in gold_set:
            counts["fn"] += 1


def _set_scores(predicted: set, gold_set: set, tp_set: set) -> dict:
    precision = len(tp_set) / len(predicted) if predicted else (
        1.0 if not gold_set else 0.0)
    recall = len(tp_set) / len(gold_set) if gold_set else 1.0
    f1 = (2 * precision * recall / (precision + recall)
          if precision + recall else 0.0)
    return {"precision": precision, "recall": recall, "f1": f1}


def _finite(value) -> Optional[float]:
    """The floor as a finite float, or None (bools/strings/NaN etc.
    are corruption, not floors — json.loads happily parses NaN)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if value == value and abs(value) != float("inf") \
        else None


def _metric_violations(mode: str, metrics: dict,
                       spec: dict) -> List[str]:
    """Per-metric floor breaches for one mode. Non-numeric floors
    read as violations — a corrupt floors file must fail loudly,
    never compare garbage against scores."""
    out: List[str] = []
    for metric in ("precision", "recall", "f1"):
        floor = _finite(spec.get(metric))
        if floor is None:
            if spec.get(metric) is not None:
                out.append(f"{mode}: {metric} floor is not a finite "
                           "number")
            continue
        if metrics[metric] < floor:
            out.append(f"{mode}: {metric} {metrics[metric]:.2f} "
                       f"< floor {floor:.2f}")
    return out


def check_floors(multi: "MultiLabelResult",
                floors: dict) -> List[str]:
    """Compare a multi-label evaluation against regression floors.

    ``floors`` follows docs/bench-floors.json: ``sample_f1`` plus a
    ``modes`` map of per-metric minimums. Returns human-readable
    violations — an empty list means the attribution quality did not
    regress past the slack each floor deliberately carries.
    """
    violations: List[str] = []
    for mode, spec in sorted((floors.get("modes") or {}).items()):
        metrics = (multi.per_mode or {}).get(mode)
        if metrics is None:
            if spec.get("required"):
                violations.append(f"{mode}: no score (required)")
            continue
        violations.extend(_metric_violations(mode, metrics, spec))
    sample_floor = _finite(floors.get("sample_f1"))
    if floors.get("sample_f1") is not None and sample_floor is None:
        violations.append("sample_f1: not a finite number")
    elif sample_floor is not None and multi.macro_f1 < sample_floor:
        violations.append(
            f"sample macro-F1 {multi.macro_f1:.2f} "
            f"< floor {sample_floor:.2f}")
    return violations


def evaluate_multi(labeled: List[tuple]) -> "MultiLabelResult":
    """Set-based evaluation over multi-gold records.

    ``labeled``: ``(trace, gold_set)`` pairs. The predictor is the set
    of MAST modes the fusion layer reports at confidence >= threshold.
    Sample-averaged set precision/recall/F1 — a sample's precision is
    |pred ∩ gold| / |pred|, its recall is |pred ∩ gold| / |gold|, and
    the averages are over samples, which treats a 5-mode gold trace
    exactly as fairly as a 1-mode one.
    """
    from .attributor import MIN_CONFIDENCE

    per_sample: List[dict] = []
    per_mode: dict = {}
    for trace, gold in labeled:
        gold_set = set(gold)
        predicted = {d.mode_id for d in run_rules(trace)
                     if d.confidence >= MIN_CONFIDENCE}
        tp_set = predicted & gold_set
        per_sample.append(_set_scores(predicted, gold_set, tp_set))
        _tally_modes(per_mode, predicted, gold_set, tp_set)
    return _summarize_multi(per_sample, per_mode)


def _summarize_multi(per_sample: List[dict], per_mode: dict
                     ) -> "MultiLabelResult":
    for mode_id, counts in per_mode.items():
        per_mode[mode_id].update(_prf(**counts))
    n = len(per_sample)
    avg_p = sum(s["precision"] for s in per_sample) / n if n else 0.0
    avg_r = sum(s["recall"] for s in per_sample) / n if n else 0.0
    avg_f1 = sum(s["f1"] for s in per_sample) / n if n else 0.0
    return MultiLabelResult(accuracy=avg_p, macro_f1=avg_f1,
                            per_mode=per_mode, samples=n,
                            sample_precision=avg_p, sample_recall=avg_r)


@dataclass
class MultiLabelResult(BenchmarkResult):
    """Set-based evaluation summary (sample-averaged P/R/F1).

    ``accuracy`` carries the sample-averaged set precision (set-based
    evaluation has no point-accuracy); ``macro_f1`` the sample-averaged
    F1 — both names keep the leaderboard renderer shared.
    """

    samples: int = 0
    sample_precision: float = 0.0
    sample_recall: float = 0.0


# ---- leaderboard rendering (v0.10) -------------------------------------------
#
# Benchmark numbers only matter if people can see them. This renders a
# BenchmarkResult as a self-contained HTML page (no JS, no CDN, same
# visual language as report.py) — run it on MAST-Data or your own labeled
# set and ship the page next to your agent.

_LEADERBOARD_CSS = """
body { font: 15px/1.55 -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
       margin: 0; background: #f6f7f9; color: #1a1d21; }
main { max-width: 860px; margin: 0 auto; padding: 32px 20px 64px; }
h1 { font-size: 24px; margin: 0 0 4px; }
.meta { color: #6c757d; font-size: 13px; margin-bottom: 22px; }
.kpis { display: flex; gap: 14px; flex-wrap: wrap; margin-bottom: 18px; }
.kpi { background: #fff; border: 1px solid #e4e7eb; border-radius: 12px;
       padding: 14px 20px; min-width: 140px; box-shadow: 0 1px 2px rgb(0 0 0 / 4%); }
.kpi .num { font-size: 26px; font-weight: 700; }
.kpi .cap { color: #868e96; font-size: 12px; text-transform: uppercase;
            letter-spacing: .06em; }
table { width: 100%; border-collapse: collapse; background: #fff;
        border: 1px solid #e4e7eb; border-radius: 12px; font-size: 13.5px; }
th { text-align: left; color: #868e96; font-weight: 600; padding: 8px 10px;
     border-bottom: 2px solid #e4e7eb; }
td { padding: 7px 10px; border-bottom: 1px solid #eef0f2; }
.bar { height: 9px; border-radius: 5px; background: #1c7430; opacity: .8;
       min-width: 2px; display: inline-block; vertical-align: middle; }
.mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; }
.ci { display: block; color: #868e96; font-size: 11px; }
footer { margin-top: 22px; color: #adb5bd; font-size: 12.5px; text-align: center; }
"""


def _prf_bar(value: float) -> str:
    """Clamped P/R/F1 bar: values outside [0, 1] or non-finite read 0/1."""
    import html as _html
    import math as _math

    v = float(value)
    if not _math.isfinite(v) or v < 0.0:
        pct = 0.0
    elif v > 1.0:
        pct = 1.0
    else:
        pct = v
    return (f'<span class="bar" style="width:{pct * 120:.0f}px"></span> '
            f"{_html.escape(f'{pct:.2f}')}")


def render_leaderboard_html(result: BenchmarkResult, source: str,
                            dataset: str = "", n: int = 0) -> str:
    """Self-contained HTML leaderboard for a :class:`BenchmarkResult`.

    Mode ids and the source/dataset strings arrive from the dataset file
    (untrusted input), so everything user-controlled is HTML-escaped.
    """
    import datetime
    import html as _html

    esc = _html.escape
    rows = []
    for mode_id, m in sorted(result.per_mode.items(),
                             key=lambda kv: -kv[1]["f1"]):
        label = get_mode(mode_id).label  # falls back to OTHER's label
        p_lo, p_hi = m.get("precision_ci", (0.0, 0.0))
        r_lo, r_hi = m.get("recall_ci", (0.0, 0.0))
        rows.append(
            "<tr>"
            f'<td class="mono">{esc(mode_id)}</td>'
            f"<td>{esc(label)}</td>"
            f"<td>{_prf_bar(m['precision'])}"
            f'<span class="ci">{p_lo:.2f}-{p_hi:.2f}</span></td>'
            f"<td>{_prf_bar(m['recall'])}"
            f'<span class="ci">{r_lo:.2f}-{r_hi:.2f}</span></td>'
            f"<td>{_prf_bar(m['f1'])}</td>"
            f'<td class="mono">{m["tp"]}/{m["fp"]}/{m["fn"]}</td>'
            "</tr>"
        )
    rows_html = "".join(rows) or '<tr><td colspan="6">no modes scored</td></tr>'
    meta = " · ".join(
        part for part in (
            f"{n} labeled traces" if n else "",
            f"predictor: {esc(source)}",
            f"dataset: {esc(dataset)}" if dataset else "",
            datetime.datetime.now(datetime.timezone.utc)
            .strftime("%Y-%m-%d %H:%M UTC"),
        ) if part
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>approximately · attribution leaderboard</title>
<style>{_LEADERBOARD_CSS}</style></head><body><main>
<h1>Attribution leaderboard</h1>
<div class="meta">{meta} · generated by approximately</div>
<div class="kpis">
  <div class="kpi"><div class="num">{result.accuracy:.1%}</div>
    <div class="cap">accuracy</div></div>
  <div class="kpi"><div class="num">{result.macro_f1:.1%}</div>
    <div class="cap">macro-F1</div></div>
  <div class="kpi"><div class="num">{len(result.per_mode)}</div>
    <div class="cap">modes scored</div></div>
</div>
<table>
<tr><th>mode</th><th>failure</th><th>precision</th><th>recall</th><th>F1</th><th>tp/fp/fn</th></tr>
{rows_html}
</table>
<footer>benchmarked with <a href="https://github.com/B1ueMu3ic4m/approximately">approximately</a>
· taxonomy: MAST (arXiv:2503.13657)</footer>
</main></body></html>"""
