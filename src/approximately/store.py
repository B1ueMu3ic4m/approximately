"""Local trace store: one JSON file per trace under a traces directory."""

from __future__ import annotations

import json
import os
import re
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


SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*\Z")


def safe_artifact(directory: Path, trace_id: str,
                  suffix: str) -> Path:
    """A derived artifact path named by the trace's id — but only
    an id the filename rules allow. ``--trace /path/to/foreign.json``
    loads a file whose ``"id"`` may be ``"../../pwn"``; without
    this gate the analysis doors become an arbitrary write."""
    if not _safe_id(trace_id):
        raise ValueError(
            f"trace id {trace_id!r} is not a safe filename; "
            "refusing to name a derived artifact with it")
    return directory / f"{trace_id}{suffix}"


def _safe_id(trace_id: str) -> bool:
    """A trace id is a NAME, not a path: one safe-token token, no
    separators, no climb, no dotfiles. Anything else is refused
    at the store boundary — save() writes ``directory/<id>.json``
    and a hostile id (shipped in, say, as a trace_ship row)
    must never turn that into an arbitrary write, and load()
    must never read past the store on one either."""
    return bool(trace_id) and bool(SAFE_ID.match(trace_id))


def _annotation_entry_verdict(entry: dict, prev: str,
                              lineno: int,
                              key: Optional[bytes]) -> "tuple":
    """One signed annotation's verdict: ('ok'|'broken'|
    'unverifiable', message). The stamp check needs the signing
    key; the link continuity never does — a rotated key leaves the
    sequence still auditable, and the wrong key blesses nothing."""
    import hmac as _hmac

    from .integrity import annotation_stamp

    stamp = entry.get("stamp", "")
    use_key = key if entry.get("key_id") else None
    if use_key is None and entry.get("key_id"):
        if entry.get("prev", "") != prev:
            return "broken", (
                f"line {lineno}: trace "
                f"{entry.get('trace_id')} breaks the link")
        return "unverifiable", None
    check = {k: v for k, v in entry.items() if k != "stamp"}
    actual = annotation_stamp(check, entry.get("prev", ""), use_key)
    if not _hmac.compare_digest(actual, stamp) \
            or entry.get("prev", "") != prev:
        return "broken", (
            f"line {lineno}: trace "
            f"{entry.get('trace_id')} does not match its chain")
    return "ok", None


def trace_files(directory: "Path") -> List["Path"]:
    """Root-level trace candidates, oldest-mtime last: every
    ``*.json`` in the store that is not furniture (the price
    catalog, the stats snapshot). The one glob every trace-facing
    pass should use — a degenerate empty-task trace parsed out of
    ``prices.json`` once polluted every fleet surface."""
    return [p for p in sorted(Path(directory).glob("*.json"),
                              key=lambda p: p.stat().st_mtime)
            if p.name not in STORE_ARTIFACTS]


def atomic_write(path: Path, text: str,
                 budget_s: float = 10.0) -> None:
    """The one artifact-write primitive: a unique tmp file in the
    target's directory written inside a bounded budget, then
    os.replace - readers see the old file or the complete new
    one, and a Windows sharing violation on the tmp (the
    indexer's favorite target) retries instead of killing the
    door after the numbers were computed."""
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    _write_bounded(tmp, text, path, budget_s)


def _write_bounded(tmp: Path, payload: str, path: Path,
                   budget_s: float = 10.0) -> None:
    """The trace file write shares the per-id lock's own budget: a
    Windows sharing violation on the tmp file (an indexer loves a
    just-created .tmp) used to raise out of save() - under
    concurrent finishers the caller's thread died silently and
    the record's ledger line never landed (the fifth CI loss)."""
    deadline = time.time() + budget_s
    while True:
        try:
            tmp.write_text(payload, encoding="utf-8")
            _replace_bounded(tmp, path)
            return
        except OSError:
            if time.time() > deadline:
                raise
            time.sleep(0.05)


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
        if not _safe_id(trace.id):
            raise ValueError(
                f"trace id {trace.id!r} is not a safe name - "
                "ids are names, not paths")
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
            _write_bounded(tmp, payload, path)
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
        """Sidecar hygiene: total and unreadable line counts, read
        from the chain walk's own tally — one pass over the file,
        one definition of "unreadable" (an absent sidecar is 0/0:
        no annotations is not a problem)."""
        path = self.directory / "annotations.jsonl"
        result = self.verify_annotations()
        return {"present": path.exists(),
                "total": result["total"],
                "corrupt": result["corrupt"]}

    def annotate(self, trace_id: str, note: str,
                 author: str = "", verdict: str = "",
                 key_file: Optional[str] = None) -> dict:
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
        from .integrity import load_key, stamp_annotation

        # the triage log is evidence too: each entry extends the
        # previous stamp (keyed when a signing key is in play,
        # plain sha256 when not), so an edited verdict or a
        # removed line breaks every later link
        stamped = stamp_annotation(entry, self._last_stamp(),
                                   load_key(key_file))
        path = self.directory / "annotations.jsonl"
        with path.open("a", encoding="utf-8") as fh:
            # ensure_ascii (the default) is load-bearing: a lone
            # surrogate in a hostile note crashes a UTF-8 write
            fh.write(json.dumps(stamped) + "\n")
        return stamped

    def _last_stamp(self) -> str:
        """The chain link the next annotation extends: the last
        line's stamp. A torn tail (a corrupt last line) starts a
        fresh segment rather than propagating a lie; an unsigned
        (legacy) tail links as empty — signed entries append
        cleanly after an upgrade."""
        path = self.directory / "annotations.jsonl"
        if not path.exists():
            return ""
        with path.open("rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            window = min(size, 4096)
            fh.seek(size - window)
            tail = fh.read().decode("utf-8", "replace")
        lines = [ln for ln in tail.splitlines() if ln.strip()]
        if not lines:
            return ""
        try:
            last = json.loads(lines[-1])
        except json.JSONDecodeError:
            return ""
        stamp = last.get("stamp") if isinstance(last, dict) else None
        return stamp if isinstance(stamp, str) else ""

    def verify_annotations(self,
                           key_file: Optional[str] = None) -> dict:
        """Recompute the annotation chain the way the writer wrote
        it: every signed entry's stamp must match its own content
        AND its ``prev`` must equal the walked previous stamp. An
        unsigned (legacy) entry verifies trivially and resets the
        link — signed entries append cleanly after an upgrade, and
        no old file ever reads as broken."""
        from .integrity import load_key

        key = load_key(key_file)
        total = signed = unsigned = unverifiable = corrupt = 0
        broken: List[str] = []
        path = self.directory / "annotations.jsonl"
        if not path.exists():
            return {"total": 0, "signed": 0, "unsigned": 0,
                    "unverifiable": 0, "corrupt": 0, "broken": []}
        prev = ""
        for lineno, raw in enumerate(
                path.read_text(encoding="utf-8").splitlines(), 1):
            line = raw.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                if not isinstance(entry, dict):
                    raise ValueError
            except ValueError:
                # a corrupt line is a torn segment: the next
                # signed entry chains from empty, exactly as the
                # writer's tail read would have linked it; total
                # counts EVERY line — the doctor's hygiene reading
                # names the unreadable subset
                prev = ""
                corrupt += 1
                total += 1
                continue
            total += 1
            stamp = entry.get("stamp")
            if not isinstance(stamp, str) or not stamp:
                unsigned += 1
                prev = ""
                continue
            signed += 1
            verdict, message = _annotation_entry_verdict(
                entry, prev, lineno, key)
            if verdict == "broken":
                broken.append(message)
            elif verdict == "unverifiable":
                unverifiable += 1
            prev = stamp
        return {"total": total, "signed": signed, "unsigned": unsigned,
                "unverifiable": unverifiable, "corrupt": corrupt,
                "broken": broken}

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
            try:
                mtime = path.stat().st_mtime
            except OSError:
                # vanished mid-pass (a parallel writer, a raced
                # rotate): nothing to age, nothing to crash on
                continue
            if mtime >= cutoff:
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
        # three shapes: an explicit .json file, an explicit path
        # that wants .json appended (the caller names it, like
        # cat — climbs still refused), and a bare safe token
        # resolved inside the store's fence. Save refuses
        # anything but the last shape: the write vector is the
        # one untrusted ids can reach.
        path = Path(trace_id)
        if ".." in path.parts:
            return None
        if path.suffix == ".json" and path.is_file():
            return path
        explicit = Path(str(path) + ".json")
        if path.suffix != ".json" and explicit.is_file():
            return explicit
        if not _safe_id(trace_id):
            return None
        candidate = self.directory / f"{trace_id}.json"
        return candidate if candidate.is_file() else None

