"""Optional LLM judge: MAST classification for traces via an OpenAI-compatible API.

The judge complements the rule detectors with semantic modes that have no
cheap mechanical signature (e.g. FM-2.6 reasoning-action mismatch). It is
strictly optional: the core package installs without ``openai`` and every
CLI path falls back to rules when the judge is unavailable.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

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
    return "\n".join(
        f"- {m.id} [{m.category_name}] {m.name}: {m.definition}"
        for m in all_modes() if m.id != OTHER
    )


@dataclass
class JudgeVerdict:
    detection: Detection
    rationale: str
    raw: str


class JudgeError(RuntimeError):
    pass


def _compact_trace(trace: Trace, max_step_chars: int = 220) -> Dict[str, Any]:
    steps = [
        {
            "i": s.index,
            "kind": s.kind,
            "tool": s.tool,
            "args": s.args,
            "result": (s.error or s.result or "")[:max_step_chars],
            "thought": (s.thought or "")[:max_step_chars] or None,
            # semantic markers the judge needs for verification modes
            "meta": {k: v for k, v in s.meta.items() if k != "_hot"} or None,
        }
        for s in trace.steps
    ]
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


def _judge_request(trace: Trace, chosen_model: str, preset: str,
                   api_key: Optional[str] = None,
                   base_url: Optional[str] = None) -> str:
    """Call the OpenAI-compatible API; every failure becomes JudgeError."""
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
        return response.choices[0].message.content or ""
    except JudgeError:
        raise
    except Exception as exc:  # auth, network, HTTP — all degrade identically
        raise JudgeError(
            f"judge call failed: {type(exc).__name__}: {exc}"
        ) from exc


def _parse_verdict(payload: dict, chosen_model: str, raw: str) -> JudgeVerdict:
    """Normalize an arbitrary judge payload into a safe Detection."""
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


def _cache_key(trace: Trace, chosen_model: str, preset: str) -> str:
    canonical = json.dumps(
        {"model": chosen_model, "preset": preset,
         "trace": _compact_trace(trace)},
        sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _cache_path(cache_dir: "Path", key: str) -> Path:
    return Path(cache_dir) / f"{key}.json"


_CACHE_STATS = {"hits": 0, "misses": 0}


def cache_stats(reset: bool = False) -> dict:
    """Hits and misses since process start (or since the last reset).

    Read after a judge-consuming command to see what the cache bought:
    `{"hits": 12, "misses": 40}` on a fresh dataset is a cold cache;
    the same dataset relabeled is `{"hits": 40, "misses": 0}`."""
    stats = dict(_CACHE_STATS)
    if reset:
        _CACHE_STATS["hits"] = 0
        _CACHE_STATS["misses"] = 0
    return stats


def _load_cached(cache_dir: "Path", key: str) -> Optional[JudgeVerdict]:
    """A cache hit must look exactly like a fresh verdict; anything
    unreadable is a miss, and the next write overwrites it."""
    try:
        data = json.loads(
            _cache_path(cache_dir, key).read_text(encoding="utf-8"))
        payload = data["payload"]
        # a cache hit must be indistinguishable from a fresh answer:
        # _parse_verdict coerces garbage (mode_id 3.5 -> OTHER,
        # dict rationale -> its repr), so validate the raw shape
        # before trusting what a poisoned entry "says"
        if not isinstance(payload, dict):
            return None
        if not isinstance(payload.get("mode_id"), str):
            return None
        if not isinstance(payload.get("rationale"), str):
            return None
        if not isinstance(payload.get("confidence"), (int, float)):
            return None
        return _parse_verdict(payload, data["model"],
                              data.get("raw", ""))
    except (OSError, ValueError, KeyError, TypeError):
        return None


def judge_trace(
    trace: Trace,
    model: Optional[str] = None,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    preset: str = "strong",
    cache_dir: Optional[Path] = None,
) -> JudgeVerdict:
    """Ask an OpenAI-compatible model to classify the failure.

    ``preset`` selects the prompt shape: ``"strong"`` (full taxonomy, for
    frontier models) or ``"local"`` (compact ids-only prompt, for small
    local models and for distillation data).

    Reads OPENAI_API_KEY / OPENAI_BASE_URL by default; ``model`` defaults to
    APPROXIMATELY_JUDGE_MODEL or "gpt-4o-mini".

    ``cache_dir`` makes repeat verdicts free: the key is a hash of
    (model, preset, compact trace), so the same failure asked twice —
    or by two commands — hits the disk once and skips the API call.
    Corrupt cache entries are misses, never errors.
    """
    chosen_model = model or os.environ.get(
        "APPROXIMATELY_JUDGE_MODEL", "gpt-4o-mini"
    )
    if cache_dir is not None:
        key = _cache_key(trace, chosen_model, preset)
        cached = _load_cached(cache_dir, key)
        if cached is not None:
            _CACHE_STATS["hits"] += 1
            return cached
        _CACHE_STATS["misses"] += 1
    raw = _judge_request(trace, chosen_model, preset,
                         api_key=api_key, base_url=base_url)
    payload = _extract_json(raw)
    verdict = _parse_verdict(payload, chosen_model, raw)
    if cache_dir is not None:
        try:
            cache = Path(cache_dir)
            cache.mkdir(parents=True, exist_ok=True)
            _cache_path(cache, key).write_text(
                json.dumps({"model": chosen_model, "preset": preset,
                            "payload": payload, "raw": raw}),
                encoding="utf-8")
        except OSError:
            pass  # a full or read-only cache must not fail the judge
    return verdict
