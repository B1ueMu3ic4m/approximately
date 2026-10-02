"""v248: every surface speaks the same money.

The spend estimate existed in `stats`, `fleet`, and the MCP tools —
but `status`, the door ops actually watch, could not price a store,
and the fleet dashboard's agents table had no p95.  One
consistency round: `status --prices` grows the est-spend line
(unpriced models counted, the ci-gate rule), and the fleet store
card's agents table carries the p95 column the CLI scorecards
already have.  No new semantics — the same numbers, on every
surface.
"""

import json

from approximately.cli import main
from approximately.fleet import render_fleet_html, survey
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _seed(path):
    store = TraceStore(path)
    for i in range(4):
        rec = Recorder(f"run {i}", model="gpt-x", store=store,
                       save=False, agent="worker")
        rec.tool("deploy", {"n": i}, tokens=2000, latency_ms=300)
        rec.respond("done", success=True)
        store.save(rec.trace)
    return store


def test_status_grows_est_spend(tmp_path, capsys):
    store = _seed(tmp_path / "s")
    prices = tmp_path / "prices.json"
    prices.write_text(json.dumps({"gpt-x": 3.0}), encoding="utf-8")
    code = main(["status", "--store", str(store.directory),
                 "--prices", str(prices), "--json"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    # 4 runs x 1 step x 2000 tokens = 8k @ $3/1k = $24
    assert payload["est_spend"] == 24.0
    assert payload["unpriced_tokens"] == 0


def test_status_counts_unpriced_models(tmp_path, capsys):
    store = _seed(tmp_path / "s")
    prices = tmp_path / "prices.json"
    prices.write_text(json.dumps({"other-model": 1.0}),
                      encoding="utf-8")
    code = main(["status", "--store", str(store.directory),
                 "--prices", str(prices), "--json"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["est_spend"] == 0.0
    assert payload["unpriced_tokens"] == 8000


def test_status_without_prices_has_no_spend(tmp_path, capsys):
    store = _seed(tmp_path / "s")
    code = main(["status", "--store", str(store.directory),
                 "--json"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["est_spend"] is None


def test_status_human_line_shows_spend(tmp_path, capsys):
    store = _seed(tmp_path / "s")
    prices = tmp_path / "prices.json"
    prices.write_text(json.dumps({"gpt-x": 3.0}), encoding="utf-8")
    code = main(["status", "--store", str(store.directory),
                 "--prices", str(prices)])
    assert code == 0
    out = capsys.readouterr().out
    assert "est $24.00" in out


def test_fleet_card_agents_table_has_p95(tmp_path, capsys):
    store = _seed(tmp_path / "s")
    summaries = survey([store.directory])
    html = render_fleet_html(summaries)
    assert "<th>p95</th>" in html
    assert "300ms" in html          # the p95 cell renders
