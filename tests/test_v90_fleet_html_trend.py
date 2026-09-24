"""v90: the fleet dashboard embeds the digest-history trend.

`fleet --fleet-html --digest-dir DIR` renders the day-level fleet
trend (sparkline, Theil-Sen verdict badge, per-day table) above the
store cards. Without a digest dir the page is byte-identical to
before.
"""

import json

from approximately.cli import build_parser
from approximately.fleet import (
    append_digest,
    digest_snapshot,
    render_fleet_html,
    summarize_trend,
    survey,
    trend_days,
)
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _store_with_digests(tmp_path):
    store = TraceStore(str(tmp_path / "s"))
    for i, ok in enumerate([True, False, False]):
        rec = Recorder(f"run {i}", save=False, agent="worker")
        rec.tool("bash", {"cmd": "x"}, result="y")
        rec.respond("done", success=ok)
        store.save(rec.trace)
    digests = tmp_path / "digests"
    for day in range(3):
        snap = digest_snapshot(survey([store.directory]))
        snap["ts"] = 86400 * 20000 + 43200 + day * 86400
        append_digest(digests, snap)
    return store, digests


def test_render_with_trend_embeds_section(tmp_path):
    store, digests = _store_with_digests(tmp_path)
    trend = summarize_trend(trend_days(digests))
    html = render_fleet_html(survey([store.directory]),
                             trend_summary=trend)
    assert "Fleet trend (digest history)" in html
    assert "slope" in html and "snapshot(s)" in html
    assert "<svg" in html  # the sparkline renders
    assert "2024-10-05" in html  # day rows present


def test_render_without_trend_unchanged(tmp_path):
    store, _ = _store_with_digests(tmp_path)
    html = render_fleet_html(survey([store.directory]))
    assert "Fleet trend" not in html


def test_cli_fleet_html_with_digest_dir(tmp_path):
    store, digests = _store_with_digests(tmp_path)
    out = tmp_path / "fleet.html"
    parser = build_parser()
    args = parser.parse_args([
        "fleet", str(store.directory), "--fleet-html", str(out),
        "--digest-dir", str(digests)])
    assert args.func(args) == 0
    page = out.read_text(encoding="utf-8")
    assert "Fleet trend (digest history)" in page


def test_cli_fleet_html_without_digest_dir_has_no_trend(tmp_path):
    store, _ = _store_with_digests(tmp_path)
    out = tmp_path / "fleet.html"
    parser = build_parser()
    args = parser.parse_args(["fleet", str(store.directory),
                              "--fleet-html", str(out)])
    assert args.func(args) == 0
    assert "Fleet trend" not in out.read_text(encoding="utf-8")


def test_digest_json_path_still_serializable(tmp_path):
    store, _ = _store_with_digests(tmp_path)
    parser = build_parser()
    args = parser.parse_args(["fleet", str(store.directory), "--json"])
    import contextlib
    import io
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        args.func(args)
    payload = json.loads(buf.getvalue())
    assert len(payload["stores"]) == 1
