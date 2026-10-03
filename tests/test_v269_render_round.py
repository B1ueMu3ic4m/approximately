"""Night VI, round 12: the verdict reads well where humans look.

``ci --format markdown`` renders a GitHub step-summary table a
pipeline can cat into $GITHUB_STEP_SUMMARY; the fleet card names the
agents the per-agent ceilings caught (v2.80.0's stamp already carried
the data — the card just reads it now).
"""

import argparse
import xml.etree.ElementTree  # noqa: F401  (used via cmd_ci only)

from approximately.budget import Budget
from approximately.cli import cmd_ci
from approximately.fleet import (
    StoreSummary,
    _breach_html,
    _breached_agents,
    survey,
    webhook_payload,
)
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _seed(store_dir, breaches=0):
    store = TraceStore(store_dir)
    for i in range(3):
        with Recorder(f"calm {i}", model="m/1", store=store) as rec:
            rec.respond("done", success=True)
    for i in range(breaches):
        budget = Budget(tokens=5, on_exceed="stamp")
        with Recorder(f"burn {i}", model="m/1", store=store,
                      budget=budget) as rec:
            rec.tool("t", tokens=500)
            rec.respond("done", success=True)
    return store


def _burned_per_agent(store_dir):
    store = TraceStore(store_dir)
    budget = Budget(per_agent={"researcher": 100})
    with Recorder("team task", model="m/1", store=store,
                  budget=budget) as rec:
        rec.tool("search", agent="researcher", tokens=500)
        rec.respond("done", success=True)
    budget2 = Budget(per_agent={"booker": 100})
    with Recorder("team task 2", model="m/1", store=store,
                  budget=budget2) as rec:
        rec.tool("book", agent="booker", tokens=500)
        rec.respond("done", success=True)
    return store


def _args(store_dir, **kw):
    argv = {"store": str(store_dir), "format": None, "json": False,
            "prices": None, "min_traces": None, "since": None}
    argv.update(kw)
    return argparse.Namespace(**argv)


def test_markdown_table_renders_the_verdict(tmp_path, capsys):
    _seed(tmp_path, breaches=1)
    rc = cmd_ci(_args(tmp_path, format="markdown",
                      max_budget_breaches=0))
    out = capsys.readouterr().out
    assert rc == 1
    assert "| gate | measured | ceiling | verdict |" in out
    assert "| budget-breaches | 1 | 0 | ❌ BREACH |" in out
    assert "| min-traces | 4 | 1 | ✅ pass |" in out


def test_markdown_all_pass(tmp_path, capsys):
    _seed(tmp_path)
    rc = cmd_ci(_args(tmp_path, format="markdown",
                      max_budget_breaches=5))
    out = capsys.readouterr().out
    assert rc == 0
    assert "❌" not in out
    assert "✅ pass" in out


def test_markdown_refusal_is_a_paragraph(tmp_path, capsys):
    empty = tmp_path / "nothing"
    empty.mkdir()
    rc = cmd_ci(_args(empty, format="markdown", max_failure_rate=0.1))
    out = capsys.readouterr().out
    assert rc == 2
    assert "refused" in out and "empty" in out
    assert "| gate |" not in out


def test_breached_agents_collected_in_stamp_order(tmp_path):
    _burned_per_agent(tmp_path)
    traces = TraceStore(tmp_path).list_traces()
    assert _breached_agents(traces) == ["researcher", "booker"]


def test_summary_and_payload_carry_the_names(tmp_path):
    _burned_per_agent(tmp_path)
    s = survey([tmp_path])[0]
    assert s.budget_breaches == 2
    assert s.breached_agents == ["researcher", "booker"]
    payload = webhook_payload([s])
    assert payload["stores"][0]["breached_agents"] == \
        ["researcher", "booker"]


def test_card_names_the_agents(tmp_path):
    _burned_per_agent(tmp_path)
    from approximately.fleet import _store_card
    html = _store_card(survey([tmp_path])[0])
    assert "budget breach(es)" in html
    assert "agents: researcher, booker" in html


def test_card_silent_for_clean_stores(tmp_path):
    _seed(tmp_path)
    assert _breach_html(survey([tmp_path])[0]) == ""


def test_card_without_agent_still_names_nothing(tmp_path):
    _seed(tmp_path, breaches=2)
    html = _breach_html(survey([tmp_path])[0])
    assert "budget breach(es) — the live rails stopped these runs" \
        in html
    assert "agents:" not in html
    s = StoreSummary(name="x", path="/x", budget_breaches=1)
    assert "agents:" not in _breach_html(s)
