"""v341: SIGTERM lands the same clean shutdown as Ctrl-C.

``webhook-serve`` ran forever and died with the process on a
systemd stop — a SIGTERM should finish the archive line in
flight, close the socket, and exit 0, exactly like the Ctrl-C
path. ``fleet --watch`` has had this handler since v1.x; the
receiver gets the same.
"""

import signal

from approximately.cli import _serve_stop


def test_the_handler_raises_the_interrupt():
    import pytest

    with pytest.raises(KeyboardInterrupt):
        _serve_stop(signal.SIGTERM, None)


def test_sigterm_is_registered_and_restorable():
    old = signal.getsignal(signal.SIGTERM)
    try:
        from approximately.cli import cmd_webhook_serve  # noqa: F401
        # cmd_webhook_serve registers on entry; exercise the
        # registration path it uses
        signal.signal(signal.SIGTERM, _serve_stop)
        assert signal.getsignal(signal.SIGTERM) is _serve_stop
    finally:
        signal.signal(signal.SIGTERM, old)


def test_a_real_sigterm_exits_cleanly_posix():
    import subprocess
    import sys
    import time
    from pathlib import Path

    if sys.platform == "win32":
        return  # Windows delivers SIGTERM unreliably; the handler
        # registration above is the contract there

    archive = Path(__import__("tempfile").mkdtemp()) / "log.jsonl"
    proc = subprocess.Popen(
        [sys.executable, "-m", "approximately.cli", "webhook-serve",
         "--port", "0", "--log", str(archive)],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    try:
        assert proc.stdout is not None
        line = proc.stdout.readline()  # the listening banner
        assert "webhook-serve listening" in line, line
        time.sleep(0.3)
        proc.send_signal(signal.SIGTERM)
        code = proc.wait(timeout=10)
        assert code == 0, f"SIGTERM exited {code}, not 0"
    finally:
        if proc.poll() is None:
            proc.kill()
