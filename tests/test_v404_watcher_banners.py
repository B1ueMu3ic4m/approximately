"""v404: the watchers say what they watch.

A silent server is a misconfiguration trap: forget the signing
key and webhook-serve quietly runs the OPEN tap; forget a
follow filter and `received --follow` quietly shows a narrowed
view that looks like the whole firehose. The watchers announce
themselves now — serve's banner names the caps it will enforce
(rate, max-rows, max-bytes, when non-default), and a follow
prints its filter set before the first row (or says
"unfiltered", honestly).
"""

import argparse
import tempfile
from pathlib import Path

from approximately.cli import _follow_print


def _follow_args(**kw):
    base = {"store": str(Path(tempfile.mkdtemp())),
            "archive": None, "limit": 20, "kind": None,
            "sender": None, "unverified_only": False,
            "include_rotated": False, "since": None, "grep": None,
            "follow": True, "interval": 0.0, "max_passes": 1,
            "json": False}
    base.update(kw)
    return argparse.Namespace(**base)


def test_a_filtered_follow_names_its_filters(capsys):
    archive = Path(tempfile.mkdtemp()) / "webhook-log.jsonl"
    archive.write_text("", encoding="utf-8")
    _follow_print(archive, _follow_args(kind="trace_ship",
                                        sender="box-a",
                                        since=100.0))
    err = capsys.readouterr().err
    assert "following" in err and "filters:" in err
    assert "kind=trace_ship" in err
    assert "sender=box-a" in err
    assert "since=100.0" in err


def test_an_unfiltered_follow_says_so(capsys):
    archive = Path(tempfile.mkdtemp()) / "webhook-log.jsonl"
    archive.write_text("", encoding="utf-8")
    _follow_print(archive, _follow_args())
    err = capsys.readouterr().err
    assert "unfiltered" in err, \
        "the whole firehose is a choice, not an accident"


def test_the_serve_banner_names_its_caps():
    from approximately.cli import _serve_banner

    args = argparse.Namespace(rate=120, rate_window=30.0,
                              max_rows=100_000,
                              max_bytes=1_048_576)
    banner = _serve_banner(args, "0.0.0.0", 8080,
                           Path("/tmp/log.jsonl"), has_key=True)
    assert "verify-only" in banner
    assert "caps: rate <= 120/30s" in banner


def test_default_caps_stay_off_the_banner():
    from approximately.cli import _serve_banner

    args = argparse.Namespace(rate=0, rate_window=60.0,
                              max_rows=100_000,
                              max_bytes=1_048_576)
    banner = _serve_banner(args, "0.0.0.0", 8080,
                           Path("/tmp/log.jsonl"), has_key=False)
    assert "OPEN (no key configured" in banner, \
        "the open tap announces itself at startup"
    assert "caps:" not in banner, \
        "defaults are not caps - no zero parade"
