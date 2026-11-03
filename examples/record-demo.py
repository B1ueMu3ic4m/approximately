"""Record a small demo store for the CI self-demonstrations.

agent-gate and agent-audit both need a store to gate/audit; this
script is their shared fixture: two ok runs and one failure, so
the gates have something real to judge. Usage:

    python examples/record-demo.py <store-dir>
"""

import sys

from approximately.recorder import Recorder
from approximately.store import TraceStore


def record(store_dir: str) -> TraceStore:
    store = TraceStore(store_dir)
    for i, ok in enumerate([True, True, False]):
        rec = Recorder(f"demo run {i}", store=store)
        rec.tool("sh", {"cmd": "deploy"}, result="ok")
        rec.respond("done", success=ok)
        store.save(rec.trace)
    return store


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: record-demo.py <store-dir>", file=sys.stderr)
        raise SystemExit(2)
    record(sys.argv[1])
    print(f"recorded 3 demo runs into {sys.argv[1]}")
