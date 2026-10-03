"""Night VI, round 19: size the rails on yesterday's burn.

``approximately budget <trace>`` replays a recorded (unbudgeted) run
against hypothetical ceilings — trip step and savings — so the
ceiling for arming rails on a new agent comes from evidence, not
vibes.  Runs that never trip say so; savings count only what the
run burned AFTER the step where it should have died.
"""

import argparse
import json

from approximately.budget import Budget, simulate
from approximately.cli import cmd_budget, main
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _recorded(tmp_path, tokens=(1_000, 2_000, 8_000, 500)):
    store = TraceStore(tmp_path / "s")
    with Recorder("the burn", model="m/1", store=store,
                  save=False) as rec:
        for i, t in enumerate(tokens):
            rec.tool(f"step{i}", {"i": i}, tokens=t)
        rec.respond("done", success=True)
    store.save(rec.trace)
    return store, rec.trace


def test_simulate_finds_the_trip_step(tmp_path):
    store, trace = _recorded(tmp_path)  # 11,500 tokens total
    result = simulate(trace, tokens=5_000)
    assert result["would_trip"] is True
    # 1k + 2k = 3k stays under; +8k = 11k trips at the third step
    assert result["trip_step"] == 2
    assert result["recorded_tokens"] == 11_500
    # saved = what burned after the trip step (the 500-token step)
    assert result["saved_tokens"] == 500


def test_simulate_usd_ceiling_with_prices(tmp_path):
    store, trace = _recorded(tmp_path)
    result = simulate(trace, usd=0.05, prices={"m/1": 0.01})
    # $0.01 + $0.02 = $0.03 under; +$0.08 = $0.11 trips at step 2
    assert result["would_trip"] is True
    assert result["trip_step"] == 2
    assert result["saved_usd"] == 0.005


def test_simulate_never_trips(tmp_path):
    store, trace = _recorded(tmp_path)
    result = simulate(trace, tokens=1_000_000)
    assert result["would_trip"] is False
    assert result["trip_step"] is None
    assert result["saved_tokens"] == 0
    assert result["saved_usd"] == 0.0


def test_simulate_validation_comes_free():
    with pytest.raises(ValueError, match="at least one ceiling"):
        Budget()


import pytest


def test_cli_door_prose_and_json(tmp_path, capsys):
    store, trace = _recorded(tmp_path)
    rc = main(["budget", trace.id, "--store", str(store.directory),
               "--tokens", "5000", "--json"])
    out = capsys.readouterr().out
    assert rc == 0
    payload = json.loads(out)
    assert payload["trip_step"] == 2
    assert payload["saved_tokens"] == 500

    rc = main(["budget", trace.id, "--store", str(store.directory),
               "--tokens", "5000"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "would trip at step 2" in out
    assert "saving 500 tokens" in out


def test_cli_door_refusals(tmp_path, capsys):
    store, trace = _recorded(tmp_path)
    rc = main(["budget", "no-such-trace", "--store",
               str(store.directory), "--tokens", "10"])
    capsys.readouterr()
    assert rc == 2
    rc = main(["budget", trace.id, "--store", str(store.directory)])
    capsys.readouterr()
    assert rc == 2  # no ceiling given
    rc = main(["budget", trace.id, "--store", str(store.directory),
               "--usd", "1.0"])
    capsys.readouterr()
    assert rc == 2  # usd without prices


def test_args_namespace_shape_matches_parser(tmp_path, capsys):
    store, trace = _recorded(tmp_path)
    args = argparse.Namespace(store=str(store.directory),
                              trace=trace.id, tokens=5_000, usd=None,
                              prices=None, json=False)
    assert cmd_budget(args) == 0
    assert "would trip at step 2" in capsys.readouterr().out
