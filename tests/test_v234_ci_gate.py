"""v234: `approximately ci` — the quality-gate door.

Teams run agents inside pipelines; a regression in the agent has to
fail the build, not merely decorate a report.  One command composes
the ceilings (failure rate, step latency, tokens, estimated spend)
into a single verdict with pipeline-native exit codes: 0 pass, 1
breach, 2 configuration error or empty store.  An empty store is
refused loudly (the v230 contract) because a gate over zero runs
proves nothing.
"""

import contextlib
import io
import json

from approximately.cli import cmd_ci, main
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _seed(path, n_ok=3, n_bad=0, tokens=0, latency_ms=10, model="gpt-x"):
    store = TraceStore(path)
    for i in range(n_ok + n_bad):
        rec = Recorder(f"run {i}", model=model, store=store, save=False)
        rec.tool("search", {"q": "x"}, tokens=tokens,
                 latency_ms=latency_ms)
        rec.respond("done", success=i < n_ok)
        store.save(rec.trace)
    return store


def _prices(tmp_path, table):
    p = tmp_path / "prices.json"
    p.write_text(json.dumps(table), encoding="utf-8")
    return str(p)


def test_failure_rate_gate(tmp_path):
    _seed(tmp_path / "s", n_ok=3, n_bad=3)
    args = _args(tmp_path / "s", max_failure_rate=0.3)
    assert cmd_ci(args) == 1                  # 0.5 > 0.3
    args = _args(tmp_path / "s", max_failure_rate=0.5)
    assert cmd_ci(args) == 0                  # at the ceiling: pass


def test_tokens_gate(tmp_path):
    _seed(tmp_path / "s", n_ok=2, tokens=400)
    assert cmd_ci(_args(tmp_path / "s", max_tokens=1000)) == 0
    assert cmd_ci(_args(tmp_path / "s", max_tokens=100)) == 1


def test_p95_latency_gate(tmp_path):
    _seed(tmp_path / "s", n_ok=3, latency_ms=100)
    assert cmd_ci(_args(tmp_path / "s", max_p95_latency_ms=150)) == 0
    assert cmd_ci(_args(tmp_path / "s", max_p95_latency_ms=50)) == 1


def test_spend_gate_prices_breach(tmp_path):
    _seed(tmp_path / "s", n_ok=2, tokens=6000, model="gpt-x")
    prices = _prices(tmp_path, {"gpt-x": 0.5})
    # 12k tokens @ $0.5/1k = $6
    assert cmd_ci(_args(tmp_path / "s", max_spend=5.0,
                        prices=prices)) == 1
    assert cmd_ci(_args(tmp_path / "s", max_spend=6.0,
                        prices=prices)) == 0


def test_spend_gate_fails_unpriced_models(tmp_path):
    # a budget you cannot compute does not hold: tokens on a model
    # with no rate breach the gate even at a huge ceiling
    _seed(tmp_path / "s", n_ok=2, tokens=500, model="mystery-1")
    prices = _prices(tmp_path, {"gpt-x": 3.0})
    assert cmd_ci(_args(tmp_path / "s", max_spend=10_000.0,
                        prices=prices)) == 1


def test_spend_gate_needs_prices(tmp_path):
    _seed(tmp_path / "s")
    assert cmd_ci(_args(tmp_path / "s", max_spend=1.0)) == 2


def test_no_ceilings_is_a_configuration_error(tmp_path):
    _seed(tmp_path / "s")
    assert cmd_ci(_args(tmp_path / "s")) == 2


def test_empty_store_refused(tmp_path):
    TraceStore(tmp_path / "s")
    args = _args(tmp_path / "s", max_tokens=10)
    assert cmd_ci(args) == 2


def test_min_traces_gate(tmp_path):
    _seed(tmp_path / "s", n_ok=2)
    args = _args(tmp_path / "s", max_tokens=10**9, min_traces=5)
    assert cmd_ci(args) == 1
    args = _args(tmp_path / "s", max_tokens=10**9, min_traces=2)
    assert cmd_ci(args) == 0


def test_json_verdict(tmp_path):
    _seed(tmp_path / "s", n_ok=3, n_bad=1, tokens=120)
    args = _args(tmp_path / "s", max_failure_rate=0.1, max_tokens=100)
    args.json = True
    with contextlib.redirect_stdout(io.StringIO()) as buf:
        assert cmd_ci(args) == 1
    payload = json.loads(buf.getvalue())
    assert payload["traces"] == 4 and payload["ok"] is False
    gates = {g["gate"]: g for g in payload["gates"]}
    assert gates["failure-rate"]["ok"] is False
    assert gates["failure-rate"]["value"] == 0.25
    assert gates["tokens"]["ok"] is False
    assert gates["min-traces"]["ok"] is True


def test_cli_door_wiring(tmp_path, capsys):
    # the real argv path: parser wiring and the exit code a CI
    # pipeline actually sees
    _seed(tmp_path / "s", n_ok=4, n_bad=1, tokens=300)
    code = main(["ci", "--store", str(tmp_path / "s"),
                 "--max-failure-rate", "0.1"])
    assert code == 1
    out = capsys.readouterr().out
    assert "FAIL failure-rate" in out
    assert "gate verdict: 1 gate(s) breached" in out


def _args(store, **kw):
    import argparse

    ns = argparse.Namespace(store=str(store), since=None,
                            prices=kw.pop("prices", None),
                            json=kw.pop("json", False))
    for key, val in kw.items():
        setattr(ns, key, val)
    return ns
