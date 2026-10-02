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
from .store import TraceStore
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
    legacy_agents: List[str] = field(default_factory=list)
    annotation_lines: int = 0
    annotation_corrupt: int = 0
    annotation_orphans: List[str] = field(default_factory=list)
    judge_cache_dir: str = ""
    judge_cache_entries: int = 0
    judge_cache_corrupt: int = 0
    spool_dir: str = ""
    spool_pending: int = 0
    spool_unparsed: List[str] = field(default_factory=list)
    chain_checked: int = 0
    chain_locked: int = 0
    chain_failed: List[str] = field(default_factory=list)

    @property
    def healthy(self) -> bool:
        return not (self.corrupt or self.id_mismatch
                    or self.stale_locks or self.temp_files
                    or self.digest_gaps
                    or self.spool_unparsed
                    or self.chain_failed
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
            "legacy_agents": self.legacy_agents,
            "annotation_lines": self.annotation_lines,
            "annotation_corrupt": self.annotation_corrupt,
            "annotation_orphans": self.annotation_orphans,
            "judge_cache_dir": self.judge_cache_dir,
            "judge_cache_entries": self.judge_cache_entries,
            "judge_cache_corrupt": self.judge_cache_corrupt,
            "spool_dir": self.spool_dir,
            "spool_pending": self.spool_pending,
            "spool_unparsed": self.spool_unparsed,
            "chain_checked": self.chain_checked,
            "chain_locked": self.chain_locked,
            "chain_failed": self.chain_failed,
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
        lines.extend(self._render_chains())
        if self.annotation_lines:
            note = f"  annotations: {self.annotation_lines} note(s)"
            if self.annotation_corrupt:
                note += f", {self.annotation_corrupt} unreadable line(s)"
            if self.annotation_orphans:
                note += (f", {len(self.annotation_orphans)} reference "
                         "missing trace(s)")
            lines.append(note)
        lines.extend(f"    orphan annotation: trace {tid}"
                     for tid in self.annotation_orphans[:5])
        if self.judge_cache_dir:
            note = (f"  judge cache: {self.judge_cache_entries} "
                    "entry(ies)")
            if self.judge_cache_corrupt:
                note += (f", {self.judge_cache_corrupt} unreadable "
                         "(they are misses; safe to delete)")
            lines.append(note)
        if self.legacy_agents:
            lines.append(
                f"  legacy meta['agent'] on {len(self.legacy_agents)} "
                "trace(s) - re-save to migrate to Step.agent")
        lines.extend(f"    stale lock: {name}"
                     for name in self.stale_locks[:5])
        lines.extend(f"    leftover temp: {name}"
                     for name in self.temp_files[:5])
        lines.extend(self._render_digests())
        if self.spool_dir:
            note = (f"  spool {self.spool_dir}: "
                    f"{self.spool_pending} pending file(s)")
            if self.spool_unparsed:
                note += (f", {len(self.spool_unparsed)} no pass "
                         "could parse:")
            lines.append(note)
        lines.extend(f"    unparsed: {name}"
                     for name in self.spool_unparsed[:5])
        return "\n".join(lines)

    def _render_ledger(self) -> str:
        if not self.ledger_present:
            return "  ledger: not in use"
        if self.ledger_intact:
            return "  ledger: intact"
        return f"  ledger: TAMPERED: {self.ledger_detail}"

    def _render_chains(self) -> List[str]:
        if not self.chain_checked:
            return []
        note = (f"  integrity chains: {self.chain_checked} verified")
        if self.chain_locked:
            note += f", {self.chain_locked} locked (need the key)"
        if self.chain_failed:
            note += f", {len(self.chain_failed)} FAILED:"
        return ([note]
                + [f"    tampered: {name}"
                   for name in self.chain_failed[:5]])

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
        steps = payload.get("steps")
        if isinstance(steps, list) and any(
            isinstance(s, dict) and isinstance(s.get("meta"), dict)
            and s["meta"].get("agent") and "agent" not in s
            for s in steps
        ):
            # pre-v0.50 identity lived in step meta; Step.agent is the
            # field detectors and the scorecard read first. Re-saving
            # the trace migrates it.
            report.legacy_agents.append(path.name)


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


def _check_judge_cache(report: DoctorReport, cache: Path) -> None:
    """Count judge-cache entries and unreadable ones. Read-only: a
    corrupt entry is already a safe miss at query time, so doctor
    only names it."""
    if not cache.is_dir():
        return
    report.judge_cache_dir = str(cache)
    entries = corrupt = 0
    for path in cache.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not (isinstance(data, dict) and "payload" in data
                    and "model" in data):
                corrupt += 1
                continue
            entries += 1
        except (OSError, ValueError):
            corrupt += 1
    report.judge_cache_entries = entries
    report.judge_cache_corrupt = corrupt


def _check_spool(spool: Path, report: DoctorReport) -> None:
    """Spool hygiene: how many files are waiting, and which ones a
    pass could not parse (they stay put by design — a human needs
    to look at them, so they count against health)."""
    from .importer import import_file
    from .spool import _spool_files

    report.spool_dir = str(spool)
    files = _spool_files(spool) if spool.is_dir() else []
    report.spool_pending = len(files)
    store = TraceStore(Path(report.store)) \
        if Path(report.store).is_dir() else None
    for path in files:
        if store is None:
            break
        try:
            import_file(path, store, dry_run=True)
        except ValueError:
            report.spool_unparsed.append(path.name)


def doctor(store: Path, digest_dir: Optional[Path] = None,
           judge_cache: Optional[Path] = None,
           spool_dir: Optional[Path] = None,
           deep: bool = False) -> DoctorReport:
    """Run every check and return the structured report.

    With ``deep`` each readable record's integrity chain is
    recomputed and compared against its stamp — a record can be
    parseable yet lie.
    """
    report = DoctorReport(store=str(store))
    _check_records(store, report)
    _check_ledger(store, report)
    _check_hygiene(store, report)
    if deep:
        _check_chains(store, report)
    if digest_dir is not None and digest_dir.is_dir():
        _check_digests(digest_dir, report)
    health = TraceStore(store).annotations_health()
    report.annotation_lines = health["total"]
    report.annotation_corrupt = health["corrupt"]
    known = {p.stem for p in Path(store).glob("*.json")}
    report.annotation_orphans = sorted({
        str(a.get("trace_id"))
        for a in TraceStore(store).annotations()
        if a.get("trace_id") and str(a.get("trace_id")) not in known
    })
    if judge_cache is not None:
        _check_judge_cache(report, judge_cache)
    if spool_dir is not None:
        _check_spool(spool_dir, report)
    return report


def _check_chains(directory: Path, report: DoctorReport) -> None:
    """Deep check: recompute every record's integrity chain.

    Keyed records without the key at hand are counted ``locked`` —
    the evidence is sealed, not broken.  Unsigned records are the
    ``unsigned`` finding already; the chain says nothing about them.
    """
    from .integrity import verify

    for path in sorted(directory.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            trace = Trace.from_dict(payload)
        except (json.JSONDecodeError, AttributeError, KeyError,
                TypeError, ValueError):
            continue          # already reported by _check_records
        result = verify(trace)
        if not result.signed:
            continue
        report.chain_checked += 1
        if result.intact:
            continue
        if result.verdict_override:
            report.chain_locked += 1
        else:
            report.chain_failed.append(path.name)


def fix_hygiene(store: Path, report: DoctorReport) -> List[str]:
    """Remove what the hygiene checks flagged: stale writer locks and
    leftover temp files. Never touches record data, the ledger, or
    digests. Returns the names actually removed (skips anything that
    vanished or refuses to unlink).
    """
    candidates = report.stale_locks + report.temp_files
    return [name for name in candidates if _try_unlink(store / name)]


def _try_unlink(path: Path) -> bool:
    try:
        path.unlink()
        return True
    except OSError:
        return False
