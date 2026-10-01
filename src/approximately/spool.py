"""Watch a spool directory and ingest whatever lands in it.

The bridge between "agents dump transcript/OTLP exports somewhere"
and a live tamper-evident store: point ``approximately spool`` at
the directory (a cron job's export folder, a shared volume, a
webhook's landing zone) and every file that appears is imported,
then moved aside — deterministic ids make re-delivery a no-op, so
at-least-once delivery is safe.

One pass =

1. every ``*.jsonl`` / ``*.json`` / ``*.otlp`` file in the directory,
2. imported with the shared sniffer (native, openai-jsonl,
   messages-list, otel — pretty or one envelope per line),
3. moved to ``done/`` (or deleted with ``--delete``) once parsed,
   left in place on parse errors so nothing is silently lost.

Files that parse but import zero traces still move: their ids are
already in the store (re-delivery), and leaving them would spin.
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from .importer import import_file
from .store import TraceStore

SPOOL_SUFFIXES = (".jsonl", ".json", ".otlp")


def _spool_files(directory: Path) -> List[Path]:
    return sorted(p for p in directory.iterdir()
                  if p.is_file() and p.suffix.lower() in SPOOL_SUFFIXES)


def _archive(path: Path, done_dir: Path, delete: bool = False) -> str:
    """Move a processed file to ``done/`` (unique name on collision)
    or delete it; returns what happened for the pass report."""
    if delete:
        path.unlink()
        return "deleted"
    done_dir.mkdir(parents=True, exist_ok=True)
    target = done_dir / path.name
    stem, suffix = path.stem, path.suffix
    n = 0
    while target.exists():
        n += 1
        target = done_dir / f"{stem}.{n}{suffix}"
    shutil.move(str(path), str(target))
    return "archived"


def _primary_mode(trace) -> Optional[str]:
    """Rule-detector attribution of a failed trace (deterministic,
    no network) — the pass report says WHAT landed, not just how
    much.  Best-effort: attribution trouble yields no label."""
    try:
        from .attributor import attribute

        report = attribute(trace)
        if report.primary_mode.id != "OTHER":
            return report.primary_mode.id
    except Exception:
        return None
    return None


def spool_pass(store: TraceStore, directory: Path,
               delete: bool = False,
               dry_run: bool = False) -> Dict[str, object]:
    """One ingest pass over ``directory``; returns the counts."""
    if not directory.is_dir():
        raise ValueError(f"no such spool directory: {directory}")
    files = _spool_files(directory)
    result: Dict[str, Any] = {
        "files": len(files), "imported": 0, "skipped": 0,
        "failures": 0, "failed_traces": 0, "archived": 0,
        "deleted": 0, "left": 0, "errors": [], "failure_modes": {},
    }
    for path in files:
        try:
            outcome = import_file(path, store, dry_run=dry_run)
        except ValueError:
            # unparseable: leave it for a human, keep spooling
            result["failures"] += 1
            result["left"] += 1
            result["errors"].append(path.name)
            continue
        result["imported"] += outcome["imported"]
        result["skipped"] += outcome["skipped"]
        failed_here = 0
        if not dry_run:
            for trace_id in outcome["trace_ids"]:
                trace = store.load(trace_id)
                if trace is not None and trace.success is False:
                    failed_here += 1
                    mode = _primary_mode(trace)
                    if mode:
                        result["failure_modes"][mode] = (
                            result["failure_modes"].get(mode, 0) + 1)
        result["failed_traces"] += failed_here
        if not dry_run:
            what = _archive(path, directory / "done", delete=delete)
            result["archived" if what == "archived" else "deleted"] += 1
    return result


def watch_spool(store: TraceStore, directory: Path,
                interval: float = 60.0, once: bool = False,
                delete: bool = False, dry_run: bool = False,
                max_passes: Optional[int] = None,
                as_json: bool = False) -> int:
    """Run passes until interrupted; exit 1 if any pass ingested a
    failed trace (the cron/CI gate), 0 otherwise.  KeyboardInterrupt
    is a clean stop."""
    passes = 0
    exit_code = 0
    while True:
        passes += 1
        outcome = spool_pass(store, directory, delete=delete,
                             dry_run=dry_run)
        if outcome["failed_traces"]:
            exit_code = 1
        if as_json:
            import json

            row = dict(outcome)
            row["pass"] = passes
            print(json.dumps(row, default=str))
        else:
            line = (f"spool pass {passes}: {outcome['files']} file(s), "
                    f"{outcome['imported']} imported, "
                    f"{outcome['skipped']} skipped, "
                    f"{outcome['failures']} unparsed")
            raw_modes: Any = outcome.get("failure_modes") or {}
            modes = dict(raw_modes) if isinstance(raw_modes, dict) \
                else {}
            if modes:
                detail = ", ".join(f"{m} x{c}"
                                   for m, c in sorted(modes.items()))
                line += f" | failures: {detail}"
            print(line)
        if once or (max_passes is not None
                    and passes >= max_passes):
            return exit_code
        try:
            time.sleep(interval)
        except KeyboardInterrupt:
            return exit_code
