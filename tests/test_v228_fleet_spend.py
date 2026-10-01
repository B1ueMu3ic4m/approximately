"""v228: the fleet sees the money — tokens and spend per store.

`fleet --prices FILE` prices every store's tokens by its traces'
recorded models, and the number reaches the store card, `fleet
--json`, and the digest snapshots (additive fields).  Without a
table the token count still shows; unpriced tokens are counted,
never silently free.
"""

import argparse
import json

import pytest

from approximately.cli import cmd_fleet
from approximately.fleet import survey
from approximately.mcp_server import ServerContext, handle_request
from approximately.store import TraceStore
from approximately.trace import Step, Trace


def _seed(path, model="gpt-x", tokens=10_000):
    store = TraceStore(path)
    trace = Trace(task="priced run", id="aaa000000000", model=model,
                  success=True)
    trace.add(Step(kind="tool_call", tool="t", tokens=tokens))
    store.save(trace)
    return store


def _prices(tmp_path):
    table = tmp_path / "prices.json"
    table.write_text(json.dumps({"gpt-x": 3.0}), encoding="utf-8")
    return table


def test_survey_carries_tokens_and_spend(tmp_path):
    store = _seed(tmp_path / "s")
    summaries = survey([store.directory], prices={"gpt-x": 3.0})
    s = summaries[0]
    assert s.total_tokens == 10_000
    assert s.est_spend == 30.0
    assert s.spend_unpriced_tokens == 0


def test_survey_without_prices_has_tokens_only(tmp_path):
    store = _seed(tmp_path / "s")
    s = survey([store.directory])[0]
    assert s.total_tokens == 10_000
    assert s.est_spend is None


def test_unpriced_models_are_counted(tmp_path):
    store = _seed(tmp_path / "s", model="mystery")
    s = survey([store.directory], prices={"gpt-x": 3.0})[0]
    assert s.est_spend == 0.0
    assert s.spend_unpriced_tokens == 10_000


def test_fleet_json_carries_spend(tmp_path, capsys):
    store = _seed(tmp_path / "s")
    table = _prices(tmp_path)
    args = argparse.Namespace(
        stores=[str(store.directory)], json=True, fleet_html=None,
        digest_dir=None, trend=False, agent=None, top_agents=3,
        watch=None, iterations=None, webhook=None,
        alert_anomalies=None, alert_tokens=None,
        alert_spend=None,
        alert_worse_than=None, fail_on_worsening=False,
        keep_days=30, prices=str(table))
    assert cmd_fleet(args) == 0
    payload = json.loads(capsys.readouterr().out)
    entry = (payload.get("stores") or [payload])[0]
    summary = entry.get("summary", entry)
    assert summary["total_tokens"] == 10_000
    assert summary["est_spend"] == 30.0


def test_fleet_card_shows_tokens_and_spend(tmp_path):
    from approximately.fleet import render_fleet_html

    store = _seed(tmp_path / "s")
    summaries = survey([store.directory], prices={"gpt-x": 3.0})
    html = render_fleet_html(summaries)
    assert "10,000 tokens" in html
    assert "est $30.00" in html


def test_bad_prices_file_exits_loud(tmp_path):
    store = _seed(tmp_path / "s")
    bad = tmp_path / "bad.json"
    bad.write_text("{ nope", encoding="utf-8")
    args = argparse.Namespace(
        stores=[str(store.directory)], json=False, fleet_html=None,
        digest_dir=None, trend=False, agent=None, top_agents=3,
        watch=None, iterations=None, webhook=None,
        alert_anomalies=None, alert_tokens=None,
        alert_spend=None,
        alert_worse_than=None, fail_on_worsening=False,
        keep_days=30, prices=str(bad))
    with pytest.raises(SystemExit) as exc:
        cmd_fleet(args)
    assert exc.value.code == 2


def test_mcp_survey_prices(tmp_path):
    store = _seed(tmp_path / "s")
    payload = handle_request({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "survey",
                   "arguments": {"stores": [str(store.directory)],
                                 "prices": json.dumps(
                                     {"gpt-x": 3.0})}},
    }, ServerContext(str(store.directory)))
    result = json.loads(payload["result"]["content"][0]["text"])
    summary = result["stores"][0]
    assert summary["total_tokens"] == 10_000
    assert summary["est_spend"] == 30.0


def test_markdown_parity_token_burn(tmp_path):
    from approximately.attributor import attribute
    from approximately.markdown_report import render_markdown

    store = TraceStore(tmp_path / "s")
    trace = Trace(task="burny", id="bbb000000000", success=False)
    for tokens in (95, 105, 90, 110, 100):
        trace.add(Step(kind="tool_call", tool="search",
                       tokens=tokens, latency_ms=40))
    trace.add(Step(kind="tool_call", tool="search", tokens=9_000,
                   latency_ms=40))
    trace.add(Step(kind="response", result="gave up"))
    store.save(trace)
    trace = store.load(trace.id)
    md = render_markdown(trace, attribute(trace), store=store)
    assert "### Token burn" in md
    assert "9000tok" in md
    assert "z=" in md
    # and the html card agrees
    from approximately.report import render_html

    html = render_html(trace, attribute(trace), store=store)
    assert "Token anomalies" in html


def test_report_timeline_and_agent_table_show_tokens(tmp_path):
    store = TraceStore(tmp_path / "s")
    trace = Trace(task="priced run", id="aaa000000000",
                  model="gpt-x", success=False)
    for tokens in (100, 200, 400):
        trace.add(Step(kind="tool_call", tool="search",
                       tokens=tokens, latency_ms=40))
    trace.add(Step(kind="response", result="gave up"))
    trace.steps[0].agent = "worker"
    store.save(trace)

    from approximately.attributor import attribute
    from approximately.report import render_html

    html = render_html(store.load(trace.id), attribute(trace),
                       store=store)
    assert "<th>tokens</th>" in html
    assert "100" in html            # the metered step's count
    assert "<td>—</td>" in html     # unmetered steps stay honest

    from approximately.fleet import render_fleet_html

    fleet_html = render_fleet_html(survey([store.directory]))
    assert "<th>tokens</th>" in fleet_html
