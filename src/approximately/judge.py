"""Optional LLM judge: MAST classification for traces via an OpenAI-compatible API.

The judge complements the rule detectors with semantic modes that have no
cheap mechanical signature (e.g. FM-2.6 reasoning-action mismatch). It is
strictly optional: the core package installs without ``openai`` and every
CLI path falls back to rules when the judge is unavailable.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .detectors import Detection
from .taxonomy import FAILURE_MODES, OTHER, all_modes
from .trace import Trace

SYSTEM_PROMPT = """You are a meticulous reviewer of LLM-agent trajectories.
Classify why the run failed using the MAST taxonomy. Reply with ONLY a JSON
object, no prose:

{"mode_id": "<FM-x.y or OTHER>", "step_index": <int>, "rationale": "<one sentence>",
 "confidence": <0..1>}

Failure modes:
{modes}
"""

LOCAL_PROMPT = """You review LLM-agent runs and name the failure mode.
Pick one id from this list:

{modes}

Answer with ONLY: {{"mode_id": "...", "step_index": <int>, "confidence": <0..1>}}
"""

# Presets for different judge models. "strong" gives the full taxonomy with
# definitions (frontier models); "local" strips to ids and names, cutting the
# prompt ~5x so 1-7B local models can hold it and answer reliably (this is
# also the prompt shape the distill exporter emits training data for).
PRESETS = {
    "strong": SYSTEM_PROMPT,
    "local": LOCAL_PROMPT,
}


def _taxonomy_block(compact: bool = False) -> str:
    if compact:
        return "\n".join(
            f"- {m.id} {m.name}"
            for m in all_modes() if m.id != OTHER
        )
    lines = []
    for m in all_modes():
        if m.id == OTHER:
            continue
        lines.append(f"- {m.id} [{m.category_name}] {m.name}: {m.definition}")
    return "\n".join(lines)


@dataclass
class JudgeVerdict:
    detection: Detection
    rationale: str
    raw: str


class JudgeError(RuntimeError):
    pass


def _compact_trace(trace: Trace, max_step_chars: int = 220) -> Dict[str, Any]:
    steps = []
    for s in trace.steps:
        steps.append(
            {
                "i": s.index,
                "kind": s.kind,
                "tool": s.tool,
                "args": s.args,
                "result": (s.error or s.result or "")[:max_step_chars],
                "thought": (s.thought or "")[:max_step_chars] or None,
            }
        )
    return {
        "task": trace.task,
        "success": trace.success,
        "final_output": (trace.final_output or "")[:300],
        "steps": steps,
    }


def _extract_json(text: str) -> Dict[str, Any]:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise JudgeError(f"judge returned no JSON object: {text[:200]}")
    return json.loads(text[start : end + 1])


def judge_trace(
    trace: Trace,
    model: Optional[str] = None,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    preset: str = "strong",
) -> JudgeVerdict:
    """Ask an OpenAI-compatible model to classify the failure.

    ``preset`` selects the prompt shape: ``"strong"`` (full taxonomy, for
    frontier models) or ``"local"`` (compact ids-only prompt, for small
    local models and for distillation data).

    Reads OPENAI_API_KEY / OPENAI_BASE_URL by default; ``model`` defaults to
    APPROXIMATELY_JUDGE_MODEL or "gpt-4o-mini".
    """
    try:
        from openai import OpenAI
    except ImportError as exc:  # pragma: no cover - environment-dependent
        raise JudgeError(
            "The judge requires the openai package: pip install 'approximately[llm]'"
        ) from exc

    try:
        client = OpenAI(
            api_key=api_key or os.environ.get("OPENAI_API_KEY"),
            base_url=base_url or os.environ.get("OPENAI_BASE_URL"),
        )
        chosen_model = model or os.environ.get(
            "APPROXIMATELY_JUDGE_MODEL", "gpt-4o-mini"
        )

        template = PRESETS.get(preset)
        if template is None:
            raise JudgeError(f"unknown preset {preset!r}; "
                             f"expected one of {sorted(PRESETS)}")
        response = client.chat.completions.create(
            model=chosen_model,
            messages=[
                {
                    "role": "system",
                    "content": template.replace(
                        "{modes}", _taxonomy_block(compact=(preset == "local"))
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(_compact_trace(trace), default=str),
                },
            ],
            temperature=0,
        )
        raw = response.choices[0].message.content or ""
    except JudgeError:
        raise
    except Exception as exc:  # auth, network, HTTP — all degrade identically
        raise JudgeError(
            f"judge call failed: {type(exc).__name__}: {exc}"
        ) from exc
    payload = _extract_json(raw)

    mode_id = str(payload.get("mode_id", OTHER))
    if mode_id not in FAILURE_MODES:
        mode_id = OTHER
    try:
        step_index = int(payload.get("step_index", 0))
    except (TypeError, ValueError):
        step_index = 0
    try:
        confidence = max(0.0, min(1.0, float(payload.get("confidence", 0.5))))
    except (TypeError, ValueError):
        confidence = 0.5
    rationale = str(payload.get("rationale", ""))

    detection = Detection(
        mode_id=mode_id,
        step_index=step_index,
        evidence=[f"judge ({chosen_model}): {rationale}"],
        confidence=confidence,
        source=f"judge:{chosen_model}",
    )
    return JudgeVerdict(detection=detection, rationale=rationale, raw=raw)
