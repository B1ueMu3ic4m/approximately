"""Night VI, round 25: the fresh doors, aligned.

``budget --agent`` sizes per-agent rails on one participant's steps;
``status --spend-ceiling`` gives the ops pulse the same forecast the
fleet trend carries.
"""

import argparse
import json

from approximately.budget import simulate
from approximately.cli import _status_payload, cmd_budget, main
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _team(tmp_path):
    store = TraceStore(tmp_path / "s")
    with Recorder("team run", model="m/1", store=store,
                  save=False) as rec:
        rec.tool("search", agent="researcher", tokens=1_000)
        rec.tool("book", agent="booker", tokens=100)
        rec.tool("search", agent="researcher", tokens=5_000)
        rec.respond("done", success=True)
    store.save(rec.trace)
    return store, rec.trace


def test_agent_scoped_simulation(tmp_path):
    _, trace = _team(tmp_path)
    result = simulate(trace, tokens=2_000, agent="researcher")
    # researcher alone: 1k + 5k trips on the third step
    assert result["would_trip"] is True
    assert result["trip_step"] == 2
    assert result["saved_tokens"] == 0  # nothing after the trip


def test_agent_scope_changes_the_answer(tmp_path):
    _, trace = _team(tmp_path)
    # ceiling 1_050: unscoped, the booker's 100 tokens push the
    # cumulative meter over on step 1; researcher-scoped, only the
    # researcher's own 1k + 5k count and the trip lands on step 2
    unscoped = simulate(trace, tokens=1_050)
    assert unscoped["trip_step"] == 1
    scoped = simulate(trace, tokens=1_050, agent="researcher")
    assert scoped["trip_step"] == 2


def test_agent_sim_requires_token_ceiling(tmp_path):
    _, trace = _team(tmp_path)
    import pytest
    with pytest.raises(ValueError, match="token ceiling"):
        simulate(trace, usd=1.0, agent="researcher")


def test_cli_budget_agent_flag(tmp_path, capsys):
    store, trace = _team(tmp_path)
    rc = main(["budget", trace.id, "--store", str(store.directory),
               "--tokens", "2000", "--agent", "researcher", "--json"])
    out = capsys.readouterr().out
    assert rc == 0
    assert json.loads(out)["trip_step"] == 2


def _digest(tmp_path, spends):
    digest = tmp_path / "d"
    digest.mkdir()
    for i, spend in enumerate(spends):
        line = json.dumps({
            "ts": 1791000000 + i * 86400,
            "stores": [{"name": "s", "path": "/x", "traces": 1,
                        "est_spend": spend,
                        "spend_unpriced_tokens": 0}],
            "worsening": []}, sort_keys=True)
        (digest / f"digest-2026100{i + 1}.jsonl").write_text(
            line + "\n", encoding="utf-8")
    return digest


def test_status_payload_carries_forecast(tmp_path):
    store = TraceStore(tmp_path / "s")
    with Recorder("calm", model="m/1", store=store) as rec:
        rec.respond("done", success=True)
    digest = _digest(tmp_path, [5.0, 15.0])
    payload = _status_payload(store, store.list_traces(), digest,
                              spend_ceiling=10.0)
    assert payload["spend_forecast"]["days_to_ceiling"] == 0


def test_status_forecast_requires_ceiling(tmp_path):
    store = TraceStore(tmp_path / "s")
    with Recorder("calm", model="m/1", store=store) as rec:
        rec.respond("done", success=True)
    digest = _digest(tmp_path, [5.0, 15.0])
    payload = _status_payload(store, store.list_traces(), digest)
    assert "spend_forecast" not in payload


def test_status_prose_renders_the_forecast(tmp_path, capsys):
    store = TraceStore(tmp_path / "s")
    with Recorder("calm", model="m/1", store=store) as rec:
        rec.respond("done", success=True)
    digest = _digest(tmp_path, [5.0, 15.0])
    args = argparse.Namespace(store=str(store.directory),
                              since=None, json=False, watch=False,
                              digest_dir=str(digest), prices=None,
                              interval=30.0, spend_ceiling=10.0)
    rc = cmd_budget(args) if False else main(
        ["status", "--store", str(store.directory),
         "--digest-dir", str(digest), "--spend-ceiling", "10.0"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "CEILING ALREADY EXCEEDED" in out
