"""Local trace store: one JSON file per trace under a traces directory."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import List, Optional

from .prices import STORE_ARTIFACTS
from .trace import Trace


def default_store_dir() -> Path:
    root = os.environ.get("APPROXIMATELY_HOME")
    if root:
        return Path(root)
    return Path.home() / ".approximately" / "traces"


def stamped_breach(meta: object) -> bool:
    """True when meta carries the live Budget rails' breach stamp.

    The single predicate behind the ci gate's
    ``--max-budget-breaches``, the fleet card and alert reasons, and
    ``clean --keep-breached``'s evidence guard; the non-dict-meta
    poison guard travels with it."""
    return (isinstance(meta, dict)
            and isinstance(meta.get("budget"), dict)
            and meta["budget"].get("exceeded") is True)


def trace_files(directory: "Path") -> List["Path"]:
    """Root-level trace candidates, oldest-mtime last: every
    ``*.json`` in the store that is not furniture (the price
    catalog, the stats snapshot). The one glob every trace-facing
    pass should use — a degenerate empty-task trace parsed out of
    ``prices.json`` once polluted every fleet surface."""
    return [p for p in sorted(Path(directory).glob("*.json"),
                              key=lambda p: p.stat().st_mtime)
            if p.name not in STORE_ARTIFACTS]


def _replace_bounded(tmp: Path, path: Path,
                     attempts: int = 100, pause_s: float = 0.01) -> None:
    """``os.replace`` with a bounded retry for Windows sharing clashes.

    POSIX replaces a file even while another handle has it open; Windows
    refuses with ``PermissionError`` (WinError 5) for as long as the
    reader holds it. A reader's ``read_text`` window is microseconds,
    so a short bounded retry absorbs the clash without masking a real
    failure — after ``attempts`` it raises through.
    """
    for attempt in range(attempts):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(pause_s)



class TraceStore:
    def __init__(self, directory: Optional[Path] = None):
        self.directory = Path(directory) if directory else default_store_dir()
        self.directory.mkdir(parents=True, exist_ok=True)

    def save(self, trace: Trace, stamp: bool = True) -> Path:
        """Atomically persist a trace; concurrent same-id saves serialize.

        Atomicity: write to a unique temp file in the same directory, then
        ``os.replace`` (atomic on POSIX and Windows) — readers see either
        the old file or the complete new one, never a partial write.
        Serialization: an OS lock file per trace id is held (via O_EXCL
        create with bounded retry) while the replace happens, so two
        agents finishing the same id do not interleave.

        With ``stamp`` (the default), a trace that carries no
        integrity block is signed on the way in — code saving through
        the store directly (adapters, scripts) gets the same evidence
        chain the recorder stamps on exit.  Ingest paths pass
        ``stamp=False``: foreign evidence must not acquire OUR chain,
        or doctor --deep would vouch for data we never measured.
        """
        if stamp and isinstance(trace.meta, dict) and \
                not trace.meta.get("integrity"):
            from .integrity import load_key, sign

            sign(trace, key=load_key())
        path = self.directory / f"{trace.id}.json"
        lock = self.directory / f".{trace.id}.lock"
        payload = trace.to_json()
        # acquire the per-id lock (bounded spin; stale locks time out)
        deadline = time.time() + 10.0
        fd = None
        # Windows maps a sharing violation on an existing lock to
        # EACCES (PermissionError) instead of EEXIST — it means the
        # same thing: someone holds the lock.  Spinning is bounded:
        # a permissions problem that never clears raises.
        permission_since = None
        try:
            while fd is None:
                try:
                    fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                except FileExistsError:
                    permission_since = None
                    if time.time() > deadline:
                        # stale lock from a crashed writer: break it.
                        # On Windows a held file cannot be unlinked
                        # (PermissionError) - keep spinning: the
                        # deadline bounds the wait either way.
                        try:
                            lock.unlink()
                        except (FileNotFoundError, PermissionError):
                            pass
                        deadline = time.time() + 10.0
                    time.sleep(0.005)
                except PermissionError:
                    now = time.time()
                    if permission_since is None:
                        permission_since = now
                    if now - permission_since > 10.0:
                        raise
                    time.sleep(0.005)
            tmp = self.directory / f".{trace.id}.{os.getpid()}.tmp"
            tmp.write_text(payload, encoding="utf-8")
            _replace_bounded(tmp, path)
        finally:
            if fd is not None:
                os.close(fd)
                try:
                    lock.unlink()
                except (FileNotFoundError, PermissionError):
                    pass
        self._ledger_append(trace)
        return path

    def annotations_health(self) -> dict:
        """Sidecar hygiene: total and unreadable line counts (absent
        sidecar is 0/0 — no annotations is not a problem)."""
        path = self.directory / "annotations.jsonl"
        if not path.exists():
            return {"present": False, "total": 0, "corrupt": 0}
        total = corrupt = 0
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line:
                continue
            total += 1
            try:
                entry = json.loads(line)
                if not isinstance(entry, dict):
                    corrupt += 1
            except json.JSONDecodeError:
                corrupt += 1
        return {"present": True, "total": total, "corrupt": corrupt}

    def annotate(self, trace_id: str, note: str,
                 author: str = "", verdict: str = "") -> dict:
        """Attach an analyst annotation to a trace (append-only).

        Annotations live in a sidecar ``annotations.jsonl`` — never in
        the trace file, so the tamper-evident hash chain stays intact
        and notes are themselves an append-only audit log (a note is
        never edited or removed, only superseded by later ones).
        ``verdict`` is free-form but normalized (stripped,
        lower-cased) so ``Confirmed`` and ``confirmed`` read as the
        same triage word; ``confirmed`` and ``false-positive`` are
        the idioms.  Non-string arguments are coerced: the CLI and
        MCP layers already stringify, but a direct API call should
        not crash on an int verdict.
        """
        entry = {"ts": time.time(), "trace_id": str(trace_id),
                 "author": str(author or ""),
                 "verdict": str(verdict or "").strip().lower(),
                 "note": str(note or "")}
        path = self.directory / "annotations.jsonl"
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return entry

    def annotations(self, trace_id: Optional[str] = None) -> list:
        """Annotations for one trace, or all of them, oldest first.

        Corrupt lines (partial write, hand editing) are skipped, not
        fatal — a triage log must survive a truncated tail.
        """
        path = self.directory / "annotations.jsonl"
        if not path.exists():
            return []
        out = []
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(entry, dict):
                continue
            if trace_id is None or entry.get("trace_id") == trace_id:
                out.append(entry)
        return out

    def _ledger_append(self, trace: Trace) -> None:
        """Opt-in evidence ledger (APPROXIMATELY_LEDGER=1).

        Appends the trace's chain-final hash to ledger.jsonl so later
        saves are visible to rollback detection (see approximately.ledger).
        Best-effort by design: a ledger failure never fails the save.
        """
        block = trace.meta if isinstance(trace.meta, dict) \
            else {}
        root = (block.get("integrity") or {}).get("final") \
            if isinstance(block.get("integrity"), dict) else None
        if not root or not os.environ.get("APPROXIMATELY_LEDGER"):
            return
        try:
            from .ledger import EvidenceLedger

            EvidenceLedger(self.directory).append(trace.id, root)
        except Exception:
            pass  # nosec B110 (ledger is best-effort; see docstring)

    def load(self, trace_id: str) -> Optional[Trace]:
        path = self._resolve(trace_id)
        if path is None or not path.exists():
            return None
        return Trace.from_json(path.read_text(encoding="utf-8"))

    def list_traces(self, since_days: Optional[int] = None) -> List[Trace]:
        """List traces oldest-first, optionally limited to a time window.

        ``since_days`` filters on the trace's own ``created_at`` (falling
        back to the file's mtime when created_at is unset) — triage
        almost always means "the last N days", not "everything ever".
        """
        import sys

        cutoff = (time.time() - since_days * 86400) if since_days else None
        out = []
        for path in trace_files(self.directory):
            try:
                trace = Trace.from_json(path.read_text(encoding="utf-8"))
            except Exception as exc:
                print(f"approximately: skipping unreadable trace {path.name}: "
                      f"{exc}", file=sys.stderr)
                continue
            if cutoff is None or self._created(trace, path) >= cutoff:
                out.append(trace)
        return out

    @staticmethod
    def _created(trace: Trace, path: "Path") -> float:
        """Trace's own creation time, falling back to file mtime."""
        return trace.created_at or path.stat().st_mtime

    def clean(self, keep_days: int,
              dry_run: bool = False,
              max_traces: Optional[int] = None,
              keep_breached: bool = False) -> int:
        """Delete traces older than *keep_days* and, with *max_traces*,
        the oldest beyond that count; returns the total removed
        (or that would be removed, with ``dry_run``).

        With ``keep_breached``, runs the live Budget rails stamped as
        breached (``meta["budget"].exceeded``) survive the pass no
        matter their age — housekeeping must not destroy breach
        evidence before the postmortem reads it.  Unreadable files
        are never kept by this guard: a poison file is not evidence.
        Root-level store artifacts (the price catalog, the stats
        snapshot) are furniture, not traces: they never age out.
        """
        cutoff = time.time() - keep_days * 86400
        removed = 0
        for path in self.directory.glob("*.json"):
            if path.name in STORE_ARTIFACTS:
                continue
            if path.stat().st_mtime >= cutoff:
                continue
            if keep_breached and self._is_breached(path):
                continue
            if not dry_run:
                path.unlink()
            removed += 1
        if max_traces is not None:
            remaining = []
            for path in self.directory.glob("*.json"):
                if path.name in STORE_ARTIFACTS:
                    continue
                try:
                    remaining.append((path.stat().st_mtime, path.name,
                                      path))
                except OSError:
                    continue
            excess = len(remaining) - max_traces
            if excess > 0:
                remaining.sort()
                for _mtime, _name, path in remaining:
                    if excess <= 0:
                        break
                    if keep_breached and self._is_breached(path):
                        continue
                    if not dry_run:
                        path.unlink()
                    removed += 1
                    excess -= 1
        return removed

    @staticmethod
    def _is_breached(path: "Path") -> bool:
        """Whether the trace file carries the live rails' breach stamp.

        Unreadable counts as NOT breached: the guard preserves
        evidence, not poison."""
        try:
            trace = Trace.from_json(path.read_text(encoding="utf-8"))
        except Exception:
            return False
        return stamped_breach(trace.meta)

    def _resolve(self, trace_id: str) -> Optional[Path]:
        path = Path(trace_id)
        # block traversal: an id may name an explicit .json file, but never
        # may it climb out of the caller's intent via parent segments
        if ".." in path.parts:
            return None
        if path.is_file():
            return path
        candidate = self.directory / f"{trace_id}.json"
        return candidate if candidate.is_file() else None

