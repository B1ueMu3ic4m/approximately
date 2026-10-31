"""The receiving end of the signed channel — and its readers.

Fleet summaries, tail failure announcements and shift digests all
travel one way: HMAC-signed JSON POSTs. ``webhook-serve`` is the
zero-dependency other end — a small HTTP server that verifies the
``X-Approximately-Signature`` header against the same ``load_key``
every poster uses, and archives what survives into a JSONL log.
The log is bounded (``--max-rows`` rotates it aside), and one
reader serves every surface: ``archive_stats`` (what /stats
answers), ``read_archive`` (the filter+tail the MCP inbox tool
and the CLI received door share), and ``follow_archive`` (the
on-call terminal's live view).

Trust rules, in order:

- a configured key (``--key-file`` or ``APPROXIMATELY_SIGNING_KEY``)
  makes the server **verify-only**: an absent, malformed or wrong
  signature is refused with 401 and never archived — an unauthenticated
  writer must not be able to seed the ops log;
- with no key configured the server accepts and archives, marking
  every row ``"verified": false`` — useful for a first look, and
  honest about what it is (an open tap, not a trust boundary);
- the body must be JSON; a hostile body is refused without crashing
  the server. Anything the poster sends rides along verbatim in the
  archived row — the log is evidence of what was received, not of
  what was true.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterator, List, Optional, Tuple

DEFAULT_MAX_BYTES = 1_048_576  # 1 MiB: alerts are small; a


# megabyte body is an attack, not an announcement
DEFAULT_MAX_ROWS = 100_000  # a long night of alerts is a few


# thousand rows; a hundred thousand is a hoard
class ReceiverState:
    """What the server needs between requests: the verifying key
    (None = accept-and-mark-unverified), the archive path, the
    request-size and archive-length bounds, and the lock that
    serializes the bookkeeping — ThreadingHTTPServer serves posts
    concurrently, and a lost increment or an interleaved log line
    is a lie in the ops record."""

    def __init__(self, archive: Path,
                 key: Optional[bytes] = None,
                 max_bytes: int = DEFAULT_MAX_BYTES,
                 max_rows: int = DEFAULT_MAX_ROWS):
        self.archive = archive
        self.key = key
        self.max_bytes = max(1, int(max_bytes))
        self.max_rows = max(0, int(max_rows))
        self.lock = threading.Lock()
        self.received = 0
        self.refused = 0
        self.appended = 0
        self.rows_on_disk = archive_stats(archive)["rows"]

    def verify(self, body: bytes,
               signature: Optional[str]) -> Tuple[bool, str]:
        """(verified, verdict) for one request. With no key the
        verdict is ``unsigned-open``; with a key, anything but the
        exact ``sha256=<hex>`` of the body is ``refused``."""
        if self.key is None:
            return False, "unsigned-open"
        if not signature or not signature.startswith("sha256="):
            return False, "refused"
        expected = hmac.new(self.key, body,
                            hashlib.sha256).hexdigest()
        got = signature[len("sha256="):]
        if hmac.compare_digest(expected, got):
            return True, "verified"
        return False, "refused"


def read_archive(archive: Path, limit: int = 20,
                 kind: Optional[str] = None,
                 unverified_only: bool = False,
                 include_rotated: bool = False,
                 since: Optional[float] = None) -> dict:
    """The archive read back with a filter: the /stats shape plus
    the most recent matching rows, newest last. Used by the
    ``received`` CLI door and the MCP inbox tool — one reader,
    every surface. ``include_rotated`` folds the previous log
    (``<archive>.1``, where rotation moves it) in ahead of the
    current one, so yesterday's night is still one query."""
    if since is not None and (isinstance(since, bool)
                              or not isinstance(since,
                                                (int, float))):
        raise ValueError("since must be a unix timestamp")
    stats = archive_stats(archive)
    paths = [archive]
    if include_rotated:
        rotated = archive.with_name(archive.name + ".1")
        if rotated.is_file():
            paths.insert(0, rotated)
    rows: list = []
    for path in paths:
        if not path.is_file():
            continue
        lines = path.read_text(
            encoding="utf-8", errors="replace").splitlines()
        rows.extend(_matching_rows(lines, kind, unverified_only,
                                   since))
    stats["rows_total"] = stats["rows"]
    keep = max(0, int(limit))
    # rows[-0:] is the whole list — a slice quirk would turn
    # "show none" into "show everything"
    stats["recent"] = rows[len(rows) - keep:] if keep else []
    return stats


def row_passes(row: dict, kind: Optional[str],
                unverified_only: bool,
                since: Optional[float]) -> bool:
    """The row filters — a hostile ``since`` was refused at the
    boundary, so the stamp check is just time arithmetic."""
    if kind is not None and row.get("kind") != kind:
        return False
    if unverified_only and row.get("verified") is True:
        return False
    if since is not None:
        stamp = row.get("received_at")
        if not (isinstance(stamp, (int, float)) and stamp >= since):
            return False
    return True


def _matching_rows(lines: list, kind: Optional[str],
                   unverified_only: bool,
                   since: Optional[float] = None) -> list:
    """The lines that pass the filter — malformed lines are
    skipped here (archive_stats already counted them) and never
    guessed at."""
    rows: list = []
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and row_passes(row, kind,
                                                 unverified_only,
                                                 since):
            rows.append(row)
    return rows


def follow_archive(archive: Path, interval: float = 1.0,
                   max_passes: Optional[int] = None
                   ) -> "Iterator[dict]":
    """Yield rows as they land, newest last — the on-call
    terminal's live view without ssh + tail -f. Offset-tracked:
    a rotation (the file shrinking under us) restarts from zero,
    so nothing is skipped twice or lost. Malformed lines are
    skipped; they were counted at write/read time."""
    import time as _time

    offset = 0
    last_ino = None
    passes = 0
    while max_passes is None or passes < max_passes:
        passes += 1
        offset, rows, last_ino = _follow_pass(archive, offset,
                                              last_ino)
        for row in rows:
            yield row
        _time.sleep(max(0.05, interval))


def _follow_pass(archive: Path, offset: int,
                 last_ino: Any) -> Tuple[int, List[dict], Any]:
    """One read pass: the rows that landed since ``offset``, the
    offset to resume from, and the identity the pass actually read
    — restarting from zero when the file's identity changed (a
    rotation via os.replace) or it shrank (a truncation). The
    identity is owned here: updating it after the pass would let a
    mid-pass rotation bless the new file with the old offset."""
    stat = _safe_stat(archive)
    new_ino = stat.st_ino if stat is not None else last_ino
    identity_changed = (stat is not None and last_ino is not None
                        and new_ino != last_ino)
    size = stat.st_size if stat is not None else 0
    if identity_changed or size < offset:
        offset = 0  # rotation or truncation: start over
    rows: List[dict] = []
    if size > offset:
        offset, rows, last_ino = _read_new_rows(archive, offset,
                                                rows, new_ino,
                                                last_ino)
    elif stat is not None:
        last_ino = new_ino
    return offset, rows, last_ino


def _safe_stat(archive: Path) -> Optional[Any]:
    """The file's stat, or None when it vanished mid-check (the
    rotation raced us between is_file and stat)."""
    try:
        return archive.stat() if archive.is_file() else None
    except OSError:
        return None


def _read_new_rows(archive: Path, offset: int, rows: List[dict],
                   new_ino: Any,
                   last_ino: Any) -> Tuple[int, List[dict], Any]:
    """Read the new lines; the vanished-file race is an
    restart-from-zero signal, the reader keeps the old identity."""
    try:
        with archive.open("r", encoding="utf-8",
                          errors="replace") as fh:
            fh.seek(offset)
            for line in fh:
                offset += len(line.encode("utf-8",
                                          errors="replace"))
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if isinstance(row, dict):
                    rows.append(row)
        last_ino = new_ino
    except OSError:
        # vanished mid-read: restart from zero on the next pass
        return 0, rows, last_ino
    return offset, rows, last_ino


def _open_log(stats: dict, archive: Path) -> Optional[str]:
    """Fill in the byte size and return the decoded text, BOM
    stripped; None when the log does not exist yet."""
    if not archive.is_file():
        return None
    raw = archive.read_bytes()
    stats["bytes"] = len(raw)
    text = raw.decode("utf-8", errors="replace")
    if text.startswith("\ufeff"):
        text = text[1:]  # a BOM is history, not poison
    return text


def _stat_row(stats: dict, row: dict) -> None:
    """One good row's census: the verified split, the kind bucket,
    the last arrival. A kind that is not a string buckets by its
    json form — the census must never crash on what arrived."""
    if row.get("verified") is True:
        stats["verified"] += 1
    else:
        stats["unverified"] += 1
    kind = row.get("kind", "?")
    if not isinstance(kind, str):
        kind = json.dumps(kind, sort_keys=True,
                          ensure_ascii=False)
    stats["kinds"][kind] = stats["kinds"].get(kind, 0) + 1
    stamp = row.get("received_at")
    if isinstance(stamp, (int, float)) and \
            (stats["last_received_at"] is None
             or stamp > stats["last_received_at"]):
        stats["last_received_at"] = stamp


def archive_stats(archive: Path) -> dict:
    """What the on-disk log actually holds — read back, not
    remembered. Rows, the verified split, the kind census, the last
    arrival and the byte size. A malformed line is counted as
    ``malformed`` and never guessed at (poison is evidence too)."""
    stats: dict = {"rows": 0, "verified": 0, "unverified": 0,
                   "malformed": 0, "kinds": {}, "bytes": 0,
                   "last_received_at": None,
                   "first_malformed": None}
    text = _open_log(stats, archive)
    if text is None:
        return stats
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError("row must be an object")
        except ValueError:
            stats["malformed"] += 1
            if stats["first_malformed"] is None:
                # the first poison, truncated: enough to recognise
                # the line, never enough to be it
                stats["first_malformed"] = line.strip()[:80]
            continue
        stats["rows"] += 1
        _stat_row(stats, row)
    return stats


def make_handler(state: ReceiverState) -> type:
    """Build a handler class bound to one ReceiverState (per-test
    servers get fresh state; nothing is class-level)."""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path == "/health":
                with state.lock:
                    self._reply(200, {"ok": True,
                                      "received": state.received,
                                      "refused": state.refused,
                                      "verify_mode": bool(state.key)})
                return
            if self.path == "/stats":
                with state.lock:
                    counters = {"ok": True,
                                "received": state.received,
                                "refused": state.refused,
                                "verify_mode": bool(state.key)}
                self._reply(200, dict(
                    counters,
                    archive=archive_stats(state.archive)))
                return
            self._reply(404, {"error": "not found"})

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", 0) or 0)
            if length > state.max_bytes:
                # refused BEFORE the read: a hostile Content-Length
                # must not buy a hostile read
                with state.lock:
                    state.refused += 1
                self._reply(413, {"error": f"body exceeds "
                                           f"{state.max_bytes} bytes"})
                return
            body = self.rfile.read(length) if length else b""
            verified, verdict = state.verify(
                body, self.headers.get("X-Approximately-Signature"))
            if verdict == "refused":
                with state.lock:
                    state.refused += 1
                self._reply(401, {"error": "bad signature"})
                return
            try:
                payload = json.loads(body.decode("utf-8"))
                if not isinstance(payload, dict):
                    raise ValueError("payload must be a JSON object")
            except (ValueError, UnicodeDecodeError):
                with state.lock:
                    state.refused += 1
                self._reply(400, {"error": "body must be a JSON "
                                           "object"})
                return
            row = {"received_at": time.time(),
                   "verified": verified,
                   "kind": payload.get("kind", "?"),
                   "payload": payload}
            with state.lock:
                if state.max_rows and (state.rows_on_disk
                                       + state.appended) \
                        >= state.max_rows:
                    # rotate: the previous log moves aside, the
                    # archive starts empty — an unbounded JSONL is
                    # a slow disk-fill, not a record
                    import os

                    rotated = state.archive.with_name(
                        state.archive.name + ".1")
                    os.replace(state.archive, rotated)
                    state.rows_on_disk = 0
                    state.appended = 0
                state.archive.parent.mkdir(parents=True, exist_ok=True)
                with state.archive.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(row, ensure_ascii=False,
                                        sort_keys=True) + "\n")
                state.received += 1
                state.appended += 1
            self._reply(200, {"received": True, "verified": verified})

        def _reply(self, status: int, body: dict) -> None:
            data = json.dumps(body).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args: Any) -> None:  # silenced
            pass

    return Handler


class ReceiverHTTPServer(ThreadingHTTPServer):
    """The receiver's listener. The listen backlog is a class
    attribute because ``listen()`` runs inside the constructor —
    setting it afterwards would decorate an already-bound socket.
    Deep backlog: a fleet's posters arrive in bursts, and the
    default queue of five resets connections before the handler
    ever sees them."""

    request_queue_size = 128


def serve(archive: Path, port: int = 0,
          key: Optional[bytes] = None,
          max_bytes: int = DEFAULT_MAX_BYTES,
          max_rows: int = DEFAULT_MAX_ROWS
          ) -> Tuple[ThreadingHTTPServer, ReceiverState]:
    """Bind the receiver; returns the server (call shutdown() from
    the controlling thread) and its state. ``max_rows`` rotates
    the archive when it fills (0 = unbounded, not advised)."""
    state = ReceiverState(archive, key=key, max_bytes=max_bytes,
                          max_rows=max_rows)
    server = ReceiverHTTPServer(("127.0.0.1", port),
                                make_handler(state))
    thread = __import__("threading").Thread(
        target=server.serve_forever, daemon=True)
    thread.start()
    return server, state
