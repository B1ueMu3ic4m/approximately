"""v408: the busy port is a refusal, not a crash.

`webhook-serve --port X` on an occupied port died with a raw
OSError traceback — the operator got a stack trace where a
next step belonged, and the door's own contract (exit 2 on a
bad port) was half-kept: a *malformed* port was refused, a
*busy* one exploded. The bind is a refusal now: the error
names the port, the reason, and the next step (another
receiver is listening there — use a different --port).
"""

import argparse
import signal
import tempfile
from pathlib import Path

from approximately.cli import cmd_webhook_serve
from approximately.receiver import serve


def _serve_args(port, **kw):
    base = {"store": str(Path(tempfile.mkdtemp())),
            "port": port, "key_file": None, "log": None,
            "max_bytes": 1_048_576, "max_rows": 100_000,
            "rate": 0, "rate_window": 60.0}
    base.update(kw)
    return argparse.Namespace(**base)


def test_a_busy_port_refuses_cleanly(capsys):

    original = signal.getsignal(signal.SIGTERM)
    server, _state = serve(Path(tempfile.mkdtemp())
                           / "webhook-log.jsonl", port=0)
    port = server.server_address[1]
    try:
        code = cmd_webhook_serve(_serve_args(port))
        err = capsys.readouterr().err
        assert code == 2, "a busy port is a misconfiguration"
        assert f"cannot bind port {port}" in err
        assert "another receiver is listening" in err
        assert "Traceback" not in err, "no raw crash"
    finally:
        server.shutdown()
        signal.signal(signal.SIGTERM, original)
