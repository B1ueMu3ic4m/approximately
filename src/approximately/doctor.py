"""Store doctor: health check for a trace store and its digest history.

A flight recorder is only useful if its evidence is readable. The
doctor walks the store the way an operator would after an incident:
are all record files parseable, does the evidence ledger still verify,
did any writer leave stale locks or temp files behind, and (given a
digest directory) are there monitoring gaps nobody noticed.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from .ledger import verify_ledger
from .trace import Trace

_STALE_LOCK_SECONDS = 3600.0


@dataclass
class DoctorReport:
    """Findings, section by section; ``healthy`` is the CI verdict."""

    store: str
    records: int = 0
    corrupt: List[str] = field(default_factory=list)
    id_mismatch: List[str] = field(default_factory=list)
    ledger_present: bool = False
    ledger_intact: Optional[bool] = None
    ledger_detail: str = ""
    stale_locks: List[str] = field(default_factory=list)
    temp_files: List[str] = field(default_factory=list)
    digest_days: int = 0
    digest_gaps: List[str] = field(default_factory=list)
    torn_lines: int = 0
    unsigned: int = 0

    @property
    def healthy(self) -> bool:
        return not (self.corrupt or self.id_mismatch
                    or self.stale_locks or self.temp_files
                    or self.digest_gaps
                    or self.ledger_intact is False)

    def to_dict(self) -> dict:
        return {
            "store": self.store,
            "healthy": self.healthy,
            "records": self.records,
            "corrupt": self.corrupt,
            "id_mismatch": self.id_mismatch,
            "ledger_present": self.ledger_present,
            "ledger_intact": self.ledger_intact,
            "ledger_detail": self.ledger_detail,
            "stale_locks": self.stale_locks,
            "temp_files": self.temp_files,
            "digest_days": self.digest_days,
            "digest_gaps": self.digest_gaps,
            "torn_lines": self.torn_lines,
            "unsigned": self.unsigned,
        }

    def render(self) -> str:
        lines = [(f"doctor: {self.store} - "
                  f"{'healthy' if self.healthy else 'PROBLEMS FOUND'}"),
                 (f"  records: {self.records} readable, "
                  f"{len(self.corrupt)} corrupt, "
                  f"{len(self.id_mismatch)} id/filename mismatch")]
        lines.extend(f"    corrupt: {name}" for name in self.corrupt[:5])
        lines.extend(f"    id mismatch: {name}"
                     for name in self.id_mismatch[:5])
        lines.append(self._render_ledger())
        if self.unsigned:
            lines.append(f"  unsigned records: {self.unsigned}")
        lines.extend(f"    stale lock: {name}"
                     for name in self.stale_locks[:5])
        lines.extend(f"    leftover temp: {name}"
                     for name in self.temp_files[:5])
        lines.extend(self._render_digests())
        return "\n".join(lines)

    def _render_ledger(self) -> str:
        if not self.ledger_present:
            return "  ledger: not in use"
        if self.ledger_intact:
            return "  ledger: intact"
        return f"  ledger: TAMPERED: {self.ledger_detail}"

    def _render_digests(self) -> List[str]:
        if not (self.digest_days or self.torn_lines):
            return []
        lines = [(f"  digests: {self.digest_days} day(s), "
                  f"{self.torn_lines} torn line(s)")]
        lines.extend(f"    gap: {gap}" for gap in self.digest_gaps[:5])
        return lines


def _check_records(directory: Path, report: DoctorReport) -> None:
    for path in sorted(directory.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            trace = Trace.from_dict(payload)
        except (json.JSONDecodeError, AttributeError, KeyError,
                TypeError, ValueError):
            report.corrupt.append(path.name)
            continue
        report.records += 1
        if trace.id != path.stem:
            report.id_mismatch.append(path.name)
        meta = payload.get("meta")
        if not isinstance(meta, dict) or not meta.get("integrity"):
            report.unsigned += 1


def _check_ledger(directory: Path, report: DoctorReport) -> None:
    if not (directory / "ledger.jsonl").is_file():
        return
    report.ledger_present = True
    check = verify_ledger(directory)
    report.ledger_intact = bool(check.intact)
    if not check.intact:
        report.ledger_detail = check.detail or \
            f"first bad line {check.first_bad_line}"


def _check_hygiene(directory: Path, report: DoctorReport) -> None:
    now = time.time()
    locks = []
    for lock in directory.glob(".*.lock"):
        try:
            age = now - lock.stat().st_mtime
        except OSError:
            age = _STALE_LOCK_SECONDS + 1.0
        if age > _STALE_LOCK_SECONDS:
            locks.append(lock.name)
    report.stale_locks = locks
    report.temp_files.extend(
        p.name for p in sorted(directory.glob(".*.tmp")))


def _check_digests(digest_dir: Path, report: DoctorReport) -> None:
    days = _digest_days(digest_dir)
    report.digest_days = len(days)
    report.torn_lines = _torn_lines(digest_dir)
    gaps = _gap_days(days)
    report.digest_gaps = gaps


def _digest_days(digest_dir: Path) -> List[str]:
    return sorted(p.stem.replace("digest-", "")
                  for p in digest_dir.glob("digest-*.jsonl")
                  if len(p.stem.replace("digest-", "")) == 8)


def _torn_lines(digest_dir: Path) -> int:
    torn = 0
    for path in digest_dir.glob("digest-*.jsonl"):
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line:
                continue
            try:
                json.loads(line)
            except json.JSONDecodeError:
                torn += 1
    return torn


def _gap_days(stamps: List[str]) -> List[str]:
    """Calendar days with no snapshot between the first and last."""
    if len(stamps) < 2:
        return []
    gaps: List[str] = []
    import datetime

    cursor = datetime.datetime.strptime(stamps[0], "%Y%m%d").date()
    last = datetime.datetime.strptime(stamps[-1], "%Y%m%d").date()
    present = set(stamps)
    while cursor < last:
        cursor += datetime.timedelta(days=1)
        key = cursor.strftime("%Y%m%d")
        if key not in present:
            gaps.append(key)
    return gaps


def doctor(store: Path, digest_dir: Optional[Path] = None) -> DoctorReport:
    """Run every check and return the structured report."""
    report = DoctorReport(store=str(store))
    _check_records(store, report)
    _check_ledger(store, report)
    _check_hygiene(store, report)
    if digest_dir is not None and digest_dir.is_dir():
        _check_digests(digest_dir, report)
    return report
