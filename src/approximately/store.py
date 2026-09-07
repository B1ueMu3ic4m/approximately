"""Local trace store: one JSON file per trace under a traces directory."""

from __future__ import annotations

import os
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
        path = self.directory / f"{trace.id}.json"
        path.write_text(trace.to_json(), encoding="utf-8")
        return path

    def load(self, trace_id: str) -> Optional[Trace]:
        path = self._resolve(trace_id)
        if path is None or not path.exists():
            return None
        return Trace.from_json(path.read_text(encoding="utf-8"))

    def list_traces(self) -> List[Trace]:
        out = []
        for path in sorted(self.directory.glob("*.json"), key=lambda p: p.stat().st_mtime):
            try:
                out.append(Trace.from_json(path.read_text(encoding="utf-8")))
            except Exception:
                continue
        return out

    def _resolve(self, trace_id: str) -> Optional[Path]:
        path = Path(trace_id)
        if path.is_file():
            return path
        candidate = self.directory / f"{trace_id}.json"
        return candidate if candidate.is_file() else None

