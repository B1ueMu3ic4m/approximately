"""Fuzz 29: degenerate archives against the /stats read path.

``archive_stats`` reads back what the receiver wrote — but the file
is on disk, and disks collect history: partial lines from a crash,
binary garbage, BOMs, CRLFs, rows whose fields lie about their
types, a gigabyte of nothing. The contract under fuzz: stats never
raises, every line lands in exactly one bucket (rows, malformed,
or skipped blank), and the counts agree with a straight recount.
"""

import json
import tempfile
from pathlib import Path

from approximately.receiver import archive_stats

WEIRD_KINDS = [None, 7, ["trace"], {"k": 1}, True, "", "  ",
               "trace_failure", "trace_failure"]


def _write(raw: bytes) -> Path:
    archive = Path(tempfile.mkdtemp()) / "webhook-log.jsonl"
    archive.write_bytes(raw)
    return archive


def test_stats_never_raises_on_hostile_lines():
    raw = (b"\xef\xbb\xbf"                              # BOM
           b'{"kind": "digest", "verified": true}\r\n'   # CRLF
           b"\x00\x01\x02\xff garbage\n"                 # binary
           b'{"kind": "digest", "verified": true}\n'
           b'{"kind": "digest", "verif')                 # crash-truncated
    stats = archive_stats(_write(raw))
    assert stats["malformed"] == 2    # binary + truncated tail
    assert stats["rows"] == 2         # BOM row + CRLF row
    assert stats["kinds"] == {"digest": 2}
    assert stats["rows"] + stats["malformed"] == 4


def test_fields_that_lie_about_their_types():
    rows = [{"kind": k, "verified": "yes",
             "received_at": ("not" if i % 2 else i * 1.5)}
            for i, k in enumerate(WEIRD_KINDS)]
    raw = "\n".join(json.dumps(r) for r in rows) + "\n"
    stats = archive_stats(_write(raw.encode()))
    assert stats["rows"] == len(WEIRD_KINDS)
    assert stats["verified"] == 0, "a lying verified is not verified"
    assert stats["unverified"] == len(WEIRD_KINDS)
    # kinds: real strings bucket as themselves; everything else is
    # bucketed by its json form (None -> "null", 7 -> "7", ...)
    assert stats["kinds"]["trace_failure"] == 2
    assert stats["kinds"]["7"] == 1 and stats["kinds"][""] == 1
    assert stats["kinds"]["  "] == 1 and stats["kinds"]["null"] == 1
    assert stats["kinds"]["true"] == 1
    assert stats["kinds"]["[\"trace\"]"] == 1
    assert stats["kinds"]["{\"k\": 1}"] == 1
    assert sum(stats["kinds"].values()) == len(WEIRD_KINDS)
    assert stats["last_received_at"] is not None, \
        "the numeric stamps count; the liar is skipped"


def test_blank_lines_are_skipped_not_counted():
    raw = b"\n\n" + json.dumps({"kind": "x",
                                "verified": True}).encode() + b"\n\n"
    stats = archive_stats(_write(raw))
    assert stats["rows"] == 1 and stats["malformed"] == 0


def test_recount_agreement_on_a_mixed_log():
    lines = []
    expect_rows = expect_bad = 0
    for i in range(50):
        if i % 5 == 0:
            lines.append("{{broken")
            expect_bad += 1
        else:
            lines.append(json.dumps({"kind": f"k{i % 3}",
                                     "verified": i % 2 == 0,
                                     "received_at": float(i)}))
            expect_rows += 1
    stats = archive_stats(
        _write(("\n".join(lines) + "\n").encode()))
    assert stats["rows"] == expect_rows
    assert stats["malformed"] == expect_bad
    assert sum(stats["kinds"].values()) == expect_rows
    assert stats["verified"] == sum(1 for i in range(50)
                                    if i % 5 and i % 2 == 0)
    assert stats["last_received_at"] == 49.0
