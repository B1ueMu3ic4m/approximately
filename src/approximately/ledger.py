"""Evidence ledger: append-only, self-chained history of integrity roots.

`verify` proves a trace's content is unchanged since it was *signed*.
It cannot prove the file is the *latest* signed state: an attacker (or
a bad sync tool) can roll a trace file back to an older, correctly
signed snapshot — every hash still checks out. The ledger closes that
gap: every save appends the trace's chain-final hash to an append-only
file whose lines are themselves hash-chained, so

- a rolled-back trace (old root, newer root recorded later) is
  detectable with `audit_rollback`,
- edits to the ledger itself are detectable with `verify_ledger`
  (its own chain breaks),
- the ledger needs no trust anchor: it lives next to the store and is
  only ever appended to.

Threat model note: an attacker with full write access can delete the
ledger or forge the whole file including its chain — the ledger raises
the cost of evidence manipulation from "re-sign one trace" to "forge
the entire history without gaps", the same escalation the HMAC tier
provides for single traces. For hostile storage, keep a copy of the
ledger (or its per-trace roots) outside the store.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from .trace import Trace

LEDGER_FILE = "ledger.jsonl"
_LEDGER_LOCK_STALE = 300.0  # a crashed appender's leftover


def _acquire_ledger_lock(ledger_path: "Path") -> "Optional[Path]":
    """O_EXCL lockfile around the ledger's read-then-append:
    duplicate seqs from concurrent finishers broke the chain
    permanently. Waits up to 30s, then proceeds unlocked (the
    historical race window, degraded but never data loss)."""
    import time as _time

    lock = ledger_path.with_name(ledger_path.name + ".lock")
    deadline = _time.monotonic() + 30.0
    while True:
        try:
            fd = os.open(str(lock),
                         os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            os.write(fd, str(os.getpid()).encode("ascii"))
            os.close(fd)
            return lock
        except FileExistsError:  # noqa: PERF203 - the retry IS the lock
            try:
                if _time.monotonic() > deadline:
                    return None
                if (_time.time() - lock.stat().st_mtime
                        > _LEDGER_LOCK_STALE):
                    lock.unlink()
                    continue
            except OSError:
                pass
            _time.sleep(0.01)



GENESIS = "0" * 64


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def ledger_path(directory: Path) -> Path:
    return Path(directory) / LEDGER_FILE


@dataclass
class LedgerEntry:
    seq: int
    trace_id: str
    root: str
    timestamp: str
    chain: str  # hash-chain over the canonical entry itself

    def to_dict(self) -> dict:
        return {
            "seq": self.seq, "trace_id": self.trace_id, "root": self.root,
            "timestamp": self.timestamp, "chain": self.chain,
        }


@dataclass
class LedgerCheck:
    entries: int = 0
    intact: bool = True
    first_bad_line: Optional[int] = None  # 1-based
    detail: str = ""


class EvidenceLedger:
    """Append-only root history for one trace store."""

    def __init__(self, directory: Path):
        self.path = ledger_path(directory)

    # -- reading ------------------------------------------------------------
    def entries(self) -> List[LedgerEntry]:
        if not self.path.is_file():
            return []
        out: List[LedgerEntry] = []
        for raw_line in self.path.read_text(
                encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
                out.append(LedgerEntry(
                    seq=int(raw["seq"]), trace_id=str(raw["trace_id"]),
                    root=str(raw["root"]), timestamp=str(raw["timestamp"]),
                    chain=str(raw["chain"]),
                ))
            except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                out.append(LedgerEntry(-1, "<corrupt>", "", "", ""))
        return out

    def history(self, trace_id: str) -> List[LedgerEntry]:
        return [e for e in self.entries() if e.trace_id == trace_id]

    def latest_root(self, trace_id: str) -> Optional[str]:
        hist = self.history(trace_id)
        return hist[-1].root if hist else None

    # -- appending ------------------------------------------------------------
    def append(self, trace_id: str, root: str) -> LedgerEntry:
        # the read-then-append holds a cross-trace lock: the store's
        # per-id locks serialize same-trace writers only, and two
        # concurrent finishers used to read the same tail and stamp
        # duplicate seqs — a broken ledger chain nothing could
        # repair (the doctor never touches the ledger). O_EXCL +
        # stale takeover, the spool's own discipline.
        lock = _acquire_ledger_lock(self.path)
        try:
            prev = self.entries()
            prev_chain = prev[-1].chain if prev else GENESIS
            entry = LedgerEntry(
                seq=(prev[-1].seq + 1) if prev else 1,
                trace_id=trace_id,
                root=root,
                timestamp=datetime.datetime.now(
                    datetime.timezone.utc).isoformat(timespec="seconds"),
                chain="",
            )
            entry.chain = _chain_entry(entry, prev_chain)
            line = json.dumps(entry.to_dict(), sort_keys=True)
            # single small line in O_APPEND mode: atomic on POSIX
            with open(self.path, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
                fh.flush()
                os.fsync(fh.fileno())
            return entry
        finally:
            if lock is not None:
                try:
                    lock.unlink()
                except OSError:
                    pass


def _chain_entry(entry: LedgerEntry, prev_chain: str) -> str:
    payload = json.dumps(
        {"seq": entry.seq, "trace_id": entry.trace_id, "root": entry.root,
         "timestamp": entry.timestamp, "prev": prev_chain},
        sort_keys=True,
    )
    return _sha(payload)


def verify_ledger(directory: Path) -> LedgerCheck:
    """Recompute the ledger's own hash chain; localize any edit."""
    ledger = EvidenceLedger(directory)
    entries = ledger.entries()
    check = LedgerCheck(entries=len(entries))
    prev = GENESIS
    for i, entry in enumerate(entries, start=1):
        if entry.seq < 0:
            check.intact = False
            check.first_bad_line = check.first_bad_line or i
            check.detail = f"line {i}: unparseable entry"
            return check
        if _chain_entry(entry, prev) != entry.chain:
            check.intact = False
            check.first_bad_line = check.first_bad_line or i
            check.detail = f"line {i}: chain mismatch (edited or removed)"
            return check
        prev = entry.chain
    check.detail = f"{len(entries)} entries verified" if entries \
        else "ledger empty"
    return check


def audit_rollback(trace: Trace, directory: Path) -> Optional[str]:
    """Detect a trace rolled back to an older (still-valid) signature.

    Returns ``"rolled-back"`` when the trace's current chain-final hash
    matches a *historical* ledger entry but newer entries were recorded
    afterwards; ``None`` when there is no rollback evidence (including
    "no ledger yet"). Caller must have verified the chain first — a
    tampered trace has a bogus root that matches nothing.
    """
    block = trace.meta.get("integrity")
    if not block:
        return None
    root = block.get("final")
    if not root:
        return None
    hist = [e.root for e in EvidenceLedger(directory).history(trace.id)]
    if len(hist) >= 2 and root in hist[:-1]:
        return "rolled-back"
    return None
