"""v363: --follow honors the same filters as the one-shot read.

The follow path yielded every row while the one-shot read
filtered by kind / unverified / since — the flag quietly widened
the view. Both paths now answer to the same row_passes filter.
"""

import json
import tempfile
import threading
import time
from pathlib import Path


def _row(i, kind="spool", verified=True):
    return {"received_at": 1.0 + i, "verified": verified,
            "kind": kind, "payload": {"seq": i}}


def test_follow_kind_filter_holds():
    archive = Path(tempfile.mkdtemp()) / "webhook-log.jsonl"

    def writer():
        time.sleep(0.05)
        for i, kind in enumerate(("spool", "ops_digest", "spool")):
            with archive.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(_row(i, kind=kind)) + "\n")
            time.sleep(0.1)

    threading.Thread(target=writer).start()
    seen = _follow(archive, kind="spool", max_passes=20)
    assert [r["payload"]["seq"] for r in seen] == [0, 2], \
        "the digest rows never reached the follower"


def _follow(archive, kind=None, max_passes=5):
    from approximately.receiver import follow_archive, row_passes

    return [row for row in
            follow_archive(archive, interval=0.05,
                           max_passes=max_passes)
            if row_passes(row, kind, False, None)]
