"""Local trace store: one JSON file per trace under a traces directory."""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import List, Optional

from .trace import Trace


def default_store_dir() -> Path:
    root = os.environ.get("APPROXIMATELY_HOME")
    if root:
        return Path(root)
    return Path.home() / ".approximately" / "traces"


class TraceStore:
    def __init__(self, directory: Optional[Path] = None):
        self.directory = Path(directory) if directory else default_store_dir()
        self.directory.mkdir(parents=True, exist_ok=True)

    def save(self, trace: Trace) -> Path:
        """Atomically persist a trace; concurrent same-id saves serialize.

        Atomicity: write to a unique temp file in the same directory, then
        ``os.replace`` (atomic on POSIX and Windows) — readers see either
        the old file or the complete new one, never a partial write.
        Serialization: an OS lock file per trace id is held (via O_EXCL
        create with bounded retry) while the replace happens, so two
        agents finishing the same id do not interleave.
        """
        path = self.directory / f"{trace.id}.json"
        lock = self.directory / f".{trace.id}.lock"
        payload = trace.to_json()
        # acquire the per-id lock (bounded spin; stale locks time out)
        deadline = time.time() + 10.0
        fd = None
        try:
            while fd is None:
                try:
                    fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                except FileExistsError:
                    if time.time() > deadline:
                        # stale lock from a crashed writer: break it
                        try:
                            lock.unlink()
                        except FileNotFoundError:
                            pass
                        deadline = time.time() + 10.0
                    time.sleep(0.005)
            tmp = self.directory / f".{trace.id}.{os.getpid()}.tmp"
            tmp.write_text(payload, encoding="utf-8")
            os.replace(tmp, path)
        finally:
            if fd is not None:
                os.close(fd)
                try:
                    lock.unlink()
                except FileNotFoundError:
                    pass
        return path

    def load(self, trace_id: str) -> Optional[Trace]:
        path = self._resolve(trace_id)
        if path is None or not path.exists():
            return None
        return Trace.from_json(path.read_text(encoding="utf-8"))

    def list_traces(self) -> List[Trace]:
        import sys

        out = []
        for path in sorted(self.directory.glob("*.json"),
                           key=lambda p: p.stat().st_mtime):
            try:
                out.append(Trace.from_json(path.read_text(encoding="utf-8")))
            except Exception as exc:
                print(f"approximately: skipping unreadable trace {path.name}: "
                      f"{exc}", file=sys.stderr)
        return out

    def clean(self, keep_days: int) -> int:
        """Delete traces older than *keep_days*; returns the count removed."""
        cutoff = time.time() - keep_days * 86400
        removed = 0
        for path in self.directory.glob("*.json"):
            if path.stat().st_mtime < cutoff:
                path.unlink()
                removed += 1
        return removed

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

