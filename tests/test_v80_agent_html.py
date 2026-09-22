"""v80: agent wave completion — per-agent sections in the HTML surfaces.

Single reports show an "Agents in this run" card when two or more
identities appear; the fleet dashboard grows a "Busiest agents" table
per store (steps / errors / touched-fail-rate, names escaped). The
card is hidden for single-identity runs where it would only repeat
the step table.
"""

import json

from approximately.attributor import attribute
from approximately.cli import build_parser
from approximately.fleet import render_fleet_html, survey
from approximately.recorder import Recorder
from approximately.report import render_html
from approximately.store import TraceStore


def _crew_store(tmp_path):
    store = TraceStore(str(tmp_path / "s"))
    for i, ok in enumerate([True, False]):
        rec = Recorder(f"crew run {i}", save=False)
        rec.plan("split work", agent="lead")
        rec.tool("search", {"q": f"q{i}"}, result="hits",
                 agent="researcher", error=None if ok else "timeout")
        rec.message("researcher", "lead", "findings", agent="researcher")
        rec.respond("done", success=ok, agent="lead")
        store.save(rec.trace)
    return store


def test_report_agents_card_renders_and_hides():
    rec = Recorder("solo", save=False)
    rec.tool("bash", {"cmd": "x"}, result="y")
    rec.respond("done", success=False)
    html = render_html(rec.trace, attribute(rec.trace))
    assert "Agents in this run" not in html  # single identity: no card

    crew = Recorder("crew", save=False)
    crew.plan("split", agent="lead")
    crew.tool("search", {"q": "x"}, result="y", agent="researcher")
    crew.respond("done", success=False, agent="lead")
    html = render_html(crew.trace, attribute(crew.trace))
    assert "Agents in this run" in html
    assert 'class="k"&gt;lead' not in html  # no double-escaping


def test_report_agents_card_escapes_names():
    crew = Recorder("crew", save=False)
    crew.plan("split", agent="<script>alert(1)</script>")
    crew.tool("search", {"q": "x"}, result="y", agent="researcher")
    crew.respond("done", success=False, agent="lead")
    html = render_html(crew.trace, attribute(crew.trace))
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_fleet_dashboard_lists_busiest_agents(tmp_path):
    store = _crew_store(tmp_path)
    summaries = survey([store.directory])
    html = render_fleet_html(summaries)
    assert "Busiest agents" in html
    assert "researcher" in html and "lead" in html
    assert "fail-rate" in html


def test_fleet_survives_stores_without_named_agents(tmp_path):
    store = TraceStore(str(tmp_path / "anon"))
    rec = Recorder("solo run", store=store)
    rec.respond("done")
    summaries = survey([store.directory])
    html = render_fleet_html(summaries)
    assert "no named agents recorded" in html


def test_cli_fleet_json_carries_top_agents(tmp_path):
    store = _crew_store(tmp_path)
    parser = build_parser()
    args = parser.parse_args(["fleet", str(store.directory), "--json"])
    rc = args.func(args)
    assert rc == 0
    payload = json.loads(_captured(args, store))
    top = payload["stores"][0]["top_agents"]
    assert {r["agent"] for r in top} <= {"lead", "researcher"}


def _captured(args, store, capsys=None):
    import contextlib
    import io

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        args.func(args)
    return buf.getvalue()
