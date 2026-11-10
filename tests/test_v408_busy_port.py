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
import tempfile
from pathlib import Path

from approximately.cli import cmd_webhook_serve


def _serve_args(port, **kw):
    base = {"store": str(Path(tempfile.mkdtemp())),
            "port": port, "key_file": None, "log": None,
            "max_bytes": 1_048_576, "max_rows": 100_000,
            "rate": 0, "rate_window": 60.0}
    base.update(kw)
    return argparse.Namespace(**base)


def test_a_busy_port_refuses_cleanly(capsys, monkeypatch):
    # the bind failure is simulated, not staged: Windows'
    # SO_REUSEADDR lets a second bind SUCCEED against an
    # active listener, so a real second bind would hang this
    # test inside the serve loop — the door's refusal path is
    # what we pin, deterministically on every OS
    def busy(*_a, **_k):
        raise OSError(48, "Address already in use")

    # the door imports serve lazily from the receiver module:
    # patch it there
    from approximately import receiver

    monkeypatch.setattr(receiver, "serve", busy)
    code = cmd_webhook_serve(_serve_args(8080))
    err = capsys.readouterr().err
    assert code == 2, "a busy port is a misconfiguration"
    assert "cannot bind port 8080" in err
    assert "another receiver is listening" in err
    assert "Traceback" not in err, "no raw crash"
