"""Batch-import foreign transcript files into a tamper-evident store.

The contrib adapters transcribe *live* framework objects; this module is
the path in for logs you already have on disk.  One JSON Lines file, one
transcript per line, three shapes:

``native``
    A serialized ``Trace`` (``{"id": ..., "task": ..., "steps": [...]}``).
``openai-jsonl``
    ``{"messages": [{"role": ..., "content": ...}, ...]}`` — the dump
    shape of the OpenAI chat API, tool messages may carry ``is_error``.
``messages-list``
    A bare JSON array of ``{"role", "content"}`` messages per line.

Foreign transcripts get deterministic ids (sha256 of the raw line), so
re-importing the same file is a no-op instead of a duplicate — the
second pass skips every trace the first one already stored.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from .store import TraceStore
from .trace import MESSAGE, OBSERVATION, RESPONSE, TOOL_CALL, Step, Trace

NATIVE = "native"
OPENAI_JSONL = "openai-jsonl"
MESSAGES_LIST = "messages-list"
_FORMATS = (NATIVE, OPENAI_JSONL, MESSAGES_LIST)


def _text(value: Any, limit: int = 4000) -> str:
    if isinstance(value, str):
        return value[:limit]
    try:
        return json.dumps(value, default=str)[:limit]
    except (TypeError, ValueError):
        return str(value)[:limit]


def sniff_format(path: Path) -> str:
    """Guess the on-disk shape from the first non-blank line."""
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"first line is not JSON: {exc}") from exc
            if isinstance(obj, list):
                return MESSAGES_LIST
            if not isinstance(obj, dict):
                raise ValueError("first line is neither object nor array")
            if "steps" in obj or ("task" in obj and "id" in obj):
                return NATIVE
            if "messages" in obj:
                return OPENAI_JSONL
            raise ValueError(
                "unrecognized transcript shape; "
                "pass --format explicitly")
    raise ValueError("file has no transcript lines")


def messages_to_steps(messages: List[Dict[str, Any]]) -> List[Step]:
    """Map chat-API messages onto the recorder's step vocabulary."""
    steps: List[Step] = []
    for msg in messages:
        role = str(msg.get("role", "user"))
        content = msg.get("content")
        for call in msg.get("tool_calls") or []:
            fn = call.get("function") or {}
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {"raw": fn.get("arguments")}
            steps.append(Step(kind=TOOL_CALL, tool=fn.get("name"),
                              args=args, index=len(steps),
                              meta={"role": role}))
        if role == "assistant":
            if content:
                steps.append(Step(kind=RESPONSE, result=_text(content),
                                  index=len(steps), meta={"role": role}))
        elif role == "tool":
            errored = bool(msg.get("is_error"))
            steps.append(Step(
                kind=OBSERVATION, tool=msg.get("name")
                or msg.get("tool_call_id"),
                result=_text(content), index=len(steps),
                error="tool reported an error" if errored else None,
                meta={"role": role}))
        else:
            steps.append(Step(kind=MESSAGE, result=_text(content),
                              index=len(steps), meta={"role": role}))
    return steps


def _foreign_trace(obj: Dict[str, Any], raw_line: str,
                   line_no: int, fmt: str) -> Trace:
    messages = obj.get("messages") or []
    if not messages:
        raise ValueError("transcript has no messages")
    task = "imported transcript"
    for msg in messages:
        if msg.get("role") == "user":
            task = _text(msg.get("content"), 200) or task
            break
    failed = any(m.get("is_error")
                 for m in messages if m.get("role") == "tool")
    trace_id = hashlib.sha256(raw_line.encode("utf-8")).hexdigest()[:12]
    return Trace(
        task=task, id=trace_id,
        steps=messages_to_steps(messages),
        success=not failed,
        final_output=None,
        meta={"imported_from": fmt, "source_line": line_no},
    )


def import_file(path: Path, store: TraceStore,
                fmt: Optional[str] = None,
                dry_run: bool = False) -> Dict[str, Any]:
    """Import every line of ``path``; malformed lines are skipped, not
    fatal.  Returns per-format counts plus the ids actually stored."""
    if fmt is None:
        fmt = sniff_format(path)
    elif fmt not in _FORMATS:
        raise ValueError(f"unknown format {fmt!r}; expected one of "
                         f"{', '.join(_FORMATS)}")
    existing = {t.id for t in store.list_traces()}
    imported: List[str] = []
    skipped = 0
    lines = 0
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for line_no, raw in enumerate(fh, start=1):
            if not raw.strip():
                continue
            lines += 1
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError:
                skipped += 1
                continue
            try:
                if fmt == NATIVE:
                    trace = Trace.from_dict(obj)
                elif fmt == MESSAGES_LIST:
                    trace = _foreign_trace({"messages": obj}, raw,
                                           line_no, fmt)
                else:
                    trace = _foreign_trace(obj, raw, line_no, fmt)
            except (AttributeError, KeyError, TypeError, ValueError):
                skipped += 1
                continue
            if trace.id in existing:
                skipped += 1
                continue
            if not dry_run:
                store.save(trace)
            existing.add(trace.id)
            imported.append(trace.id)
    return {"format": fmt, "lines": lines, "imported": len(imported),
            "skipped": skipped, "trace_ids": imported}
