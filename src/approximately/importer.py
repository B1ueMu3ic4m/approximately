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
``otel``
    An OTLP ``ExportTraceServiceRequest`` document — the shape
    :func:`approximately.exporter.export_otlp` writes (one compact
    envelope per line) and what tracing backends export.  A
    pretty-printed document is recognized too; anything else in that
    shape is a loud error, not a silent skip.

Foreign transcripts get deterministic ids (sha256 of the raw line), so
re-importing the same file is a no-op instead of a duplicate — the
second pass skips every trace the first one already stored.  Lines that
carry our own export metadata (``metadata.task`` / ``metadata.trace_id``,
or the OTLP ``approximately.trace.id`` attribute) roundtrip losslessly:
the original task and id are restored.
"""

from __future__ import annotations

import hashlib
import json
from itertools import chain
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .store import TraceStore
from .trace import ERROR, MESSAGE, OBSERVATION, PLAN, RESPONSE, TOOL_CALL, Step, Trace

NATIVE = "native"
OPENAI_JSONL = "openai-jsonl"
MESSAGES_LIST = "messages-list"
OTEL = "otel"
_FORMATS = (NATIVE, OPENAI_JSONL, MESSAGES_LIST, OTEL)
_META_PREFIX = "approximately.meta."
# ingest is untrusted input: without these caps a crafted envelope
# turns the store into the DoS (300k attribute keys, a 200k-step
# trace punishing every downstream command)
_MAX_IMPORTED_META = 128
_MAX_IMPORTED_STEPS = 10_000


def _loads(text: str):
    """``json.loads`` with the recursion bomb defused: Python's parser
    raises RecursionError past ~1000 nesting levels, and import
    callers contractually expect ValueError for malformed input —
    never a crash."""
    try:
        return json.loads(text)
    except RecursionError as exc:
        raise ValueError("JSON nested too deeply") from exc


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
        first = None
        for line in fh:
            if line.strip():
                first = line
                break
    if first is None:
        raise ValueError("file has no transcript lines")
    try:
        obj = _loads(first)
    except ValueError:
        if first.strip() == "{":
            return OTEL      # one pretty-printed document
        raise ValueError(
            f"first line is not JSON: {first[:40]!r}") from None
    return _sniff_object(obj)


def _sniff_object(obj: Any) -> str:
    if isinstance(obj, list):
        return MESSAGES_LIST
    if not isinstance(obj, dict):
        raise ValueError("first line is neither object nor array")
    if "resourceSpans" in obj:
        return OTEL
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


# ---------------------------------------------------------------- OTLP


def _otlp_value(container: Dict[str, Any]) -> Any:
    for key in ("stringValue", "boolValue", "intValue", "doubleValue"):
        if key in container:
            return container[key]
    return None


def _span_attrs(span: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for attr in span.get("attributes") or []:
        if isinstance(attr, dict) and "key" in attr:
            out[str(attr["key"])] = _otlp_value(attr.get("value") or {})
    return out


def _nanos(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _attr_text(attrs: Dict[str, Any], key: str,
               limit: int = 4000) -> str:
    """An attribute as text; absent means empty (never ``"null"`` —
    ``_text`` stringifies None, which would invent content)."""
    value = attrs.get(key)
    return _text(value, limit) if value is not None else ""


def _valid_id(candidate: Any) -> Optional[str]:
    if (isinstance(candidate, str) and len(candidate) == 12
            and all(c in "0123456789abcdef" for c in candidate)):
        return candidate
    return None


def _span_step(span: Dict[str, Any]) -> Step:
    """One span back onto a recorder step; spans that carry none of
    our attributes (a foreign backend's spans) land as message steps
    that keep the span name."""
    attrs = _span_attrs(span)
    kind = attrs.get("approximately.kind")
    tool = attrs.get("approximately.tool")
    start = _nanos(span.get("startTimeUnixNano"))
    end = _nanos(span.get("endTimeUnixNano"))
    latency = max(0, (end - start) // 1_000_000)
    name = _attr_text({"name": span.get("name")}, "name", 200)
    if kind == "tool_call":
        raw_args = attrs.get("approximately.args")
        try:
            args = json.loads(raw_args) if raw_args else {}
        except json.JSONDecodeError:
            args = {"raw": raw_args}
        if not isinstance(args, dict):
            args = {"raw": str(args)}
        return Step(kind=TOOL_CALL, tool=_text(tool, 200) or name,
                    args=args, latency_ms=latency)
    if kind == "observation":
        return Step(kind=OBSERVATION, tool=_text(tool, 200) or name,
                    result=_attr_text(attrs, "approximately.result"),
                    error=_attr_text(attrs, "approximately.error")
                    or None,
                    latency_ms=latency)
    if kind == "response":
        return Step(kind=RESPONSE, latency_ms=latency,
                    result=_attr_text(attrs, "approximately.result"))
    if kind == "plan":
        return Step(kind=PLAN, latency_ms=latency,
                    thought=_attr_text(attrs, "approximately.thought"))
    if kind == "error":
        return Step(kind=ERROR, latency_ms=latency,
                    error=_attr_text(attrs, "approximately.error")
                    or "error")
    if kind == "message":
        role = attrs.get(_META_PREFIX + "role")
        return Step(kind=MESSAGE,
                    result=_attr_text(attrs, "approximately.result"),
                    latency_ms=latency,
                    meta={"role": str(role or "user")})
    return Step(kind=MESSAGE, result=name or "span",
                meta={"span_name": name}, latency_ms=latency)


def _group_trace(trace_key: str,
                 spans: List[Dict[str, Any]]) -> Tuple[Trace, int]:
    roots = [s for s in spans if not s.get("parentSpanId")]
    root = roots[0] if roots else spans[0]
    attrs = _span_attrs(root)
    task = (_attr_text(attrs, "approximately.task", 200)
            or _text(root.get("name"), 200) or "imported trace")
    trace_id = (_valid_id(attrs.get("approximately.trace.id"))
                or hashlib.sha256(
                    trace_key.encode("utf-8")).hexdigest()[:12])
    raw_code = (root.get("status") or {}).get("code")
    code = 0
    if raw_code is not None:
        try:
            code = int(raw_code)
        except (TypeError, ValueError):
            code = 0
    success = False if code == 2 else True if code == 1 else None
    meta: Dict[str, Any] = {}
    for key, value in attrs.items():
        if key.startswith(_META_PREFIX) and isinstance(
                value, (str, int, float, bool)):
            if len(meta) >= _MAX_IMPORTED_META:
                break
            meta[key[len(_META_PREFIX):]] = value
    meta["imported_from"] = "otel"
    children = sorted((s for s in spans if s is not root),
                      key=lambda s: _nanos(s.get("startTimeUnixNano")))
    truncated = max(0, len(children) - _MAX_IMPORTED_STEPS)
    children = children[:_MAX_IMPORTED_STEPS]
    trace = Trace(
        task=task, id=trace_id,
        created_at=_nanos(root.get("startTimeUnixNano")) / 1e9,
        model=_attr_text(attrs, "approximately.model", 100)
        or "unknown",
        steps=[_span_step(s) for s in children],
        success=success,
        final_output=_attr_text(attrs, "approximately.final_output",
                                200) or None,
        meta=meta,
    )
    return trace, truncated


def otlp_to_traces(document: Any) -> Tuple[List[Trace], int, int, int]:
    """One OTLP document onto traces; returns (traces, malformed span
    count, spans seen, steps dropped to the per-trace cap)."""
    if not isinstance(document, dict):
        raise ValueError("OTLP document must be a JSON object")
    if not isinstance(document.get("resourceSpans"), list):
        raise ValueError("not an OTLP trace document: "
                         "missing resourceSpans")
    groups: Dict[str, List[Dict[str, Any]]] = {}
    seen = 0
    for resource in document["resourceSpans"]:
        if not isinstance(resource, dict):
            seen += 1          # counted, not fatal: an envelope that
            continue           # is shaped right stays importable
        for scope in resource.get("scopeSpans") or []:
            if not isinstance(scope, dict):
                continue
            for span in scope.get("spans") or []:
                seen += 1
                if isinstance(span, dict) and span.get("traceId"):
                    groups.setdefault(str(span["traceId"]),
                                      []).append(span)
    pairs = [_group_trace(key, spans) for key, spans in groups.items()]
    traces = [t for t, _ in pairs]
    traces.sort(key=lambda t: t.id)
    truncated = sum(n for _, n in pairs)
    grouped = sum(len(v) for v in groups.values())
    return traces, seen - grouped, seen, truncated


def _save_otlp(document: Any, store: TraceStore, dry_run: bool = False,
               existing: Optional[set] = None) -> Tuple[Dict[str, int],
                                                        List[str]]:
    traces, malformed, spans, truncated = otlp_to_traces(document)
    if existing is None:
        existing = {t.id for t in store.list_traces()}
    imported: List[str] = []
    duplicates = 0
    for trace in traces:
        if trace.id in existing:
            duplicates += 1
            continue
        if not dry_run:
            store.save(trace)
        existing.add(trace.id)
        imported.append(trace.id)
    counts = {"lines": spans, "imported": len(imported),
              "skipped": duplicates + malformed + truncated,
              "malformed": malformed, "duplicates": duplicates,
              "truncated": truncated}
    return counts, imported


def _import_otlp_lines(raw_lines: Iterable[str], store: TraceStore,
                       dry_run: bool = False) -> Dict[str, Any]:
    """OTLP in: one pretty-printed document, or compact envelopes one
    per line (the shape our exporter writes)."""
    lines = list(raw_lines)
    if lines and lines[0].strip() == "{":
        try:
            doc = _loads("".join(lines))
        except ValueError as exc:
            raise ValueError(
                f"OTLP document is not valid JSON: {exc}") from exc
        whole_counts, whole_ids = _save_otlp(doc, store,
                                             dry_run=dry_run)
        return {"format": OTEL, **whole_counts,
                "trace_ids": whole_ids}
    existing = {t.id for t in store.list_traces()}
    imported: List[str] = []
    malformed = duplicates = 0
    spans = truncated = 0
    for raw in lines:
        if not raw.strip():
            continue
        try:
            doc = _loads(raw)
        except ValueError:
            malformed += 1
            continue
        if not (isinstance(doc, dict) and "resourceSpans" in doc):
            # an explicit --format otel asserts the shape: a parsed
            # line that is not an envelope is a loud error, not a
            # silent skip
            raise ValueError(
                "not an OTLP envelope: missing resourceSpans")
        try:
            counts, ids = _save_otlp(doc, store, dry_run=dry_run,
                                     existing=existing)
        except ValueError:
            # envelope-shaped but broken inside: a counted skip,
            # never a crash
            malformed += 1
            continue
        imported.extend(ids)
        duplicates += counts["duplicates"]
        malformed += counts["malformed"]
        truncated += counts["truncated"]
        spans += counts["lines"]
    return {"format": OTEL, "lines": spans, "imported": len(imported),
            "skipped": duplicates + malformed + truncated,
            "malformed": malformed, "duplicates": duplicates,
            "truncated": truncated, "trace_ids": imported}

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
        result = import_lines(sys.stdin, store, fmt=fmt,
                              dry_run=dry_run)  # streamed
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
    """Expand each argument as a literal path, a glob pattern, or a
    directory (a directory means every ``*.jsonl`` inside it)."""
    import glob as _glob

    files: List[Path] = []
    for pattern in patterns:
        path = Path(pattern)
        if path.is_dir():
            matches = sorted(str(p) for p in path.glob("*.jsonl"))
        elif any(c in pattern for c in "*?["):
            matches = sorted(_glob.glob(pattern))
        else:
            matches = [pattern]
        for match in matches:
            candidate = Path(match)
            if candidate.is_file() and candidate not in files:
                files.append(candidate)
    return files


def import_lines(raw_lines: Iterable[str], store: TraceStore,
                 fmt: Optional[str] = None,
                 dry_run: bool = False) -> Dict[str, Any]:
    """Import transcript lines (a file's content or stdin); malformed
    lines are skipped, not fatal. Returns counts and stored ids."""
    if fmt is not None and fmt not in _FORMATS:
        raise ValueError(f"unknown format {fmt!r}; expected one of "
                         f"{', '.join(_FORMATS)}")
    if fmt is None:
        first = None
        for raw in raw_lines:
            if not raw.strip():
                continue
            first = raw
            break
        if first is None:
            raise ValueError("no transcript lines to sniff")
        try:
            obj = _loads(first)
        except ValueError as exc:
            # a pretty-printed OTLP document starts with a bare "{"
            if first.strip() == "{":
                if not isinstance(raw_lines, (list, tuple)):
                    raw_lines = chain([first], raw_lines)
                return _import_otlp_lines(raw_lines, store,
                                          dry_run=dry_run)
            raise ValueError(
                f"first line is not JSON: {exc}") from exc
        fmt = _sniff_object(obj)
        # raw_lines may be a one-pass stream (stdin): put the sniffed
        # line back at the head instead of materializing everything;
        # lists are re-iterable and must not be wrapped
        if not isinstance(raw_lines, (list, tuple)):
            raw_lines = chain([first], raw_lines)
        if fmt == OTEL:
            return _import_otlp_lines(raw_lines, store,
                                      dry_run=dry_run)
    if fmt == OTEL:
        return _import_otlp_lines(raw_lines, store, dry_run=dry_run)
    existing = {t.id for t in store.list_traces()}
    imported: List[str] = []
    malformed = duplicates = 0
    lines = 0
    for line_no, raw in enumerate(raw_lines, start=1):
        if not raw.strip():
            continue
        lines += 1
        try:
            trace = _parse_line(_loads(raw), raw, line_no, fmt)
        except (AttributeError, KeyError, TypeError, ValueError,
                json.JSONDecodeError):
            malformed += 1
            continue
        if trace.id in existing:
            duplicates += 1
            continue
        if not dry_run:
            store.save(trace)
        existing.add(trace.id)
        imported.append(trace.id)
    return {"format": fmt, "lines": lines, "imported": len(imported),
            "skipped": malformed + duplicates,
            "malformed": malformed, "duplicates": duplicates,
            "trace_ids": imported}


def import_annotations(path: Path, store: TraceStore) -> Dict[str, Any]:
    """Merge a foreign annotation sidecar: append-only, so only rows
    the store has never seen are added (exact row match on the
    whole entry). Returns the counts."""
    def _key(row):
        # stable identity: timestamps differ between stores, the
        # triage content does not
        return (str(row.get("trace_id")), str(row.get("note", "")),
                str(row.get("author", "") or ""),
                str(row.get("verdict", "") or ""))

    existing = {_key(r) for r in store.annotations()}
    added = skipped = 0
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            if not raw.strip():
                continue
            try:
                row = json.loads(raw)
            except json.JSONDecodeError:
                skipped += 1
                continue
            if not isinstance(row, dict) or not row.get("trace_id"):
                skipped += 1
                continue
            if _key(row) in existing:
                skipped += 1
                continue
            store.annotate(str(row["trace_id"]),
                           str(row.get("note", "")),
                           author=str(row.get("author", "") or ""),
                           verdict=str(row.get("verdict", "") or ""))
            existing.add(_key(row))
            added += 1
    return {"added": added, "skipped": skipped}


def import_file(path: Path, store: TraceStore,
                fmt: Optional[str] = None,
                dry_run: bool = False) -> Dict[str, Any]:
    """Import every line of ``path``; malformed lines are skipped, not
    fatal.  Returns per-format counts plus the ids actually stored."""
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        return import_lines(list(fh), store, fmt=fmt, dry_run=dry_run)
