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
second pass skips every trace the first one already stored.  Lines that
carry our own export metadata (``metadata.task`` / ``metadata.trace_id``)
roundtrip losslessly: the original task and id are restored.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .store import TraceStore
from .trace import ERROR, MESSAGE, OBSERVATION, RESPONSE, TOOL_CALL, Step, Trace

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
            return _sniff_object(obj)
    raise ValueError("file has no transcript lines")


def _sniff_object(obj: Any) -> str:
    if isinstance(obj, list):
        return MESSAGES_LIST
    if not isinstance(obj, dict):
        raise ValueError("first line is neither object nor array")
    if "steps" in obj or ("task" in obj and "id" in obj):
        return NATIVE
    if "messages" in obj:
        return OPENAI_JSONL
    raise ValueError("unrecognized transcript shape; "
                     "pass --format explicitly")


def _tool_call_step(call: Dict[str, Any], role: str) -> Step:
    fn = call.get("function") or {}
    try:
        args = json.loads(fn.get("arguments") or "{}")
    except json.JSONDecodeError:
        args = {"raw": fn.get("arguments")}
    return Step(kind=TOOL_CALL, tool=fn.get("name"), args=args,
                meta={"role": role})


def _message_steps(msg: Dict[str, Any]) -> List[Step]:
    """Map one chat-API message onto 0..n recorder steps."""
    role = str(msg.get("role", "user"))
    content = msg.get("content")
    steps: List[Step] = []
    for call in msg.get("tool_calls") or []:
        step = _tool_call_step(call, role)
        step.index = len(steps)
        steps.append(step)
    if role == "assistant":
        if msg.get("is_error"):
            # our exporter spells a failed step this way; empty
            # content still roundtrips as a failed step
            steps.append(Step(kind=ERROR, error=_text(content),
                              index=len(steps), meta={"role": role}))
        elif content is not None:
            steps.append(Step(kind=RESPONSE, result=_text(content),
                              index=len(steps), meta={"role": role}))
    elif role == "tool":
        errored = bool(msg.get("is_error"))
        steps.append(Step(
            kind=OBSERVATION, tool=msg.get("name") or msg.get("tool_call_id"),
            result=_text(content),
            error="tool reported an error" if errored else None,
            index=len(steps), meta={"role": role}))
    else:
        steps.append(Step(kind=MESSAGE, result=_text(content),
                          index=len(steps), meta={"role": role}))
    return steps


def messages_to_steps(messages: List[Dict[str, Any]]) -> List[Step]:
    """Map chat-API messages onto the recorder's step vocabulary."""
    steps: List[Step] = []
    for msg in messages:
        steps.extend(_message_steps(msg))
    return _renumber(steps)


def _renumber(steps: List[Step]) -> List[Step]:
    for i, step in enumerate(steps):
        step.index = i
    return steps


def _identity(obj: Dict[str, Any], task: str,
              raw_line: str) -> Tuple[str, str]:
    """Deterministic sha256 id; our own export metadata restores the
    original task and id so export→import roundtrips losslessly."""
    trace_id = hashlib.sha256(raw_line.encode("utf-8")).hexdigest()[:12]
    metadata = obj.get("metadata")
    if not isinstance(metadata, dict):
        return task, trace_id
    task = str(metadata.get("task") or task)
    candidate = metadata.get("trace_id")
    if (isinstance(candidate, str) and len(candidate) == 12
            and all(c in "0123456789abcdef" for c in candidate)):
        trace_id = candidate
    return task, trace_id


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
    task, trace_id = _identity(obj, task, raw_line)
    metadata = obj.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    stated = metadata.get("success", "absent")
    if isinstance(stated, bool):
        success = stated
    elif stated == "absent":
        success = not failed
    else:                       # explicit null: an open trace stays open
        success = None
    return Trace(
        task=task, id=trace_id,
        steps=messages_to_steps(messages),
        success=success,
        final_output=None,
        meta={"imported_from": fmt, "source_line": line_no},
    )


def _parse_line(obj: Any, raw: str, line_no: int,
                fmt: str) -> Trace:
    if fmt == NATIVE:
        return Trace.from_dict(obj)
    if fmt == MESSAGES_LIST:
        return _foreign_trace({"messages": obj}, raw, line_no, fmt)
    return _foreign_trace(obj, raw, line_no, fmt)

def _merge(per_file: List[Dict[str, Any]], result: Dict[str, Any],
           name: str, totals: Dict[str, int],
           total_ids: List[str]) -> None:
    row = {"file": name, **{
        k: result[k] for k in ("format", "lines", "imported",
                               "skipped")}}
    if "error" in result:
        row["error"] = result["error"]
    per_file.append(row)
    total_ids.extend(result["trace_ids"])
    totals["lines"] += result["lines"]
    totals["imported"] += result["imported"]
    totals["skipped"] += result["skipped"]


def import_paths(patterns: List[str], store: TraceStore,
                 fmt: Optional[str] = None,
                 dry_run: bool = False,
                 jobs: int = 1) -> Dict[str, Any]:
    """Import transcript files named by the patterns; ``-`` reads
    stdin. Per-file counts ride along in ``per_file``.

    ``jobs > 1`` imports files on a thread pool — store saves are
    atomic and lock-serialized, so parallel ingest is safe; identical
    transcripts arriving twice in flight collapse to one trace (same
    deterministic id)."""
    per_file: List[Dict[str, Any]] = []
    total_ids: List[str] = []
    totals = {"lines": 0, "imported": 0, "skipped": 0}
    files = 0
    patterns = list(patterns)
    stdin_pending = "-" in patterns
    patterns = [p for p in patterns if p != "-"]
    paths = _expand(patterns)
    if not paths and not stdin_pending:
        raise ValueError("no files matched: "
                         + ", ".join(patterns) if patterns
                         else "nothing to import")
    if stdin_pending:
        import sys

        files += 1
        result = import_lines(list(sys.stdin), store, fmt=fmt,
                              dry_run=dry_run)
        _merge(per_file, result, "<stdin>", totals, total_ids)
    errors = 0

    tolerate = len(paths) > 1  # one bad file must not kill a batch,
    # but a single named file that cannot be parsed stays a loud error

    def import_one(path):
        nonlocal errors
        try:
            return import_file(path, store, fmt=fmt, dry_run=dry_run)
        except ValueError as exc:
            if not tolerate:
                raise
            errors += 1
            return {"format": "?", "lines": 0, "imported": 0,
                    "skipped": 0, "trace_ids": [],
                    "error": str(exc)}

    if jobs > 1 and len(paths) > 1:
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=min(jobs, len(paths))) \
                as pool:
            for path, result in zip(
                    paths,
                    pool.map(import_one, paths)):
                files += 1
                _merge(per_file, result, str(path), totals, total_ids)
    else:
        for path in paths:
            files += 1
            _merge(per_file, import_one(path), str(path), totals,
                   total_ids)
    return {"files": files, "errors": errors, **totals,
            "trace_ids": total_ids, "per_file": per_file}


def _expand(patterns: List[str]) -> List[Path]:
    """Expand each argument as a literal path or a glob pattern."""
    import glob as _glob

    files: List[Path] = []
    for pattern in patterns:
        matches = sorted(_glob.glob(pattern)) if any(
            c in pattern for c in "*?[") else [pattern]
        for match in matches:
            path = Path(match)
            if path.is_file() and path not in files:
                files.append(path)
    return files


def import_lines(raw_lines: List[str], store: TraceStore,
                 fmt: Optional[str] = None,
                 dry_run: bool = False) -> Dict[str, Any]:
    """Import transcript lines (a file's content or stdin); malformed
    lines are skipped, not fatal. Returns counts and stored ids."""
    if fmt is not None and fmt not in _FORMATS:
        raise ValueError(f"unknown format {fmt!r}; expected one of "
                         f"{', '.join(_FORMATS)}")
    if fmt is None:
        for raw in raw_lines:
            if not raw.strip():
                continue
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"first line is not JSON: {exc}") from exc
            fmt = _sniff_object(obj)
            break
        else:
            raise ValueError("no transcript lines to sniff")
    existing = {t.id for t in store.list_traces()}
    imported: List[str] = []
    skipped = 0
    lines = 0
    for line_no, raw in enumerate(raw_lines, start=1):
        if not raw.strip():
            continue
        lines += 1
        try:
            trace = _parse_line(json.loads(raw), raw, line_no, fmt)
        except (AttributeError, KeyError, TypeError, ValueError,
                json.JSONDecodeError):
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


def import_file(path: Path, store: TraceStore,
                fmt: Optional[str] = None,
                dry_run: bool = False) -> Dict[str, Any]:
    """Import every line of ``path``; malformed lines are skipped, not
    fatal.  Returns per-format counts plus the ids actually stored."""
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        return import_lines(list(fh), store, fmt=fmt, dry_run=dry_run)
