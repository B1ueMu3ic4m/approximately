"""v253: `approximately compare` — did this deployment get worse?

Two stores in, one verdict out: the baseline (last known good) vs
the candidate (this deployment).  The regression signal is a
failure MODE the baseline never showed — rate thresholds wobble
with sample size, but a mode that did not exist yesterday is a
fact.  `--fail-on-new-modes` turns that fact into an exit 1 a CI
pipeline can gate on; `--prices` adds the spend delta.
"""

import json

from approximately.cli import main
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _seed(path, *, search_fails=0, deploy_fails=0, n_ok=4, model="gpt-x"):
    store = TraceStore(path)
    for i in range(n_ok):
        rec = Recorder(f"run {i}", model=model, store=store,
                       save=False)
        rec.tool("search", {"q": i}, tokens=100, latency_ms=100)
        rec.respond("done", success=True)
        store.save(rec.trace)
    for i in range(search_fails):
        rec = Recorder(f"search fail {i}", model=model, store=store,
                       save=False)
        rec.tool("search", {"q": "x"}, tokens=100, latency_ms=100,
                 error="timeout")
        rec.respond("gave up", success=False)
        store.save(rec.trace)
    for i in range(deploy_fails):
        # repeated identical call: FM-1.3 owns the primary verdict,
        # distinct from the FM-3.1 the search failures carry
        rec = Recorder(f"deploy fail {i}", model=model, store=store,
                       save=False)
        rec.tool("deploy", {"env": "prod"}, tokens=50,
                 latency_ms=200)
        rec.tool("deploy", {"env": "prod"}, tokens=50,
                 latency_ms=200)
        rec.respond("rolled back", success=False)
        store.save(rec.trace)
    return store


def test_compare_reports_no_new_modes(tmp_path, capsys):
    _seed(tmp_path / "base", search_fails=1)
    _seed(tmp_path / "cand", search_fails=2)
    code = main(["compare", "--baseline", str(tmp_path / "base"),
                 "--candidate", str(tmp_path / "cand")])
    assert code == 0
    assert "no new failure modes" in capsys.readouterr().out


def test_compare_flags_new_failure_modes(tmp_path, capsys):
    _seed(tmp_path / "base", search_fails=1)
    _seed(tmp_path / "cand", search_fails=1, deploy_fails=1)
    code = main(["compare", "--baseline", str(tmp_path / "base"),
                 "--candidate", str(tmp_path / "cand")])
    assert code == 0
    out = capsys.readouterr().out
    assert "NEW failure modes" in out


def test_fail_on_new_modes_gates_ci(tmp_path, capsys):
    _seed(tmp_path / "base", search_fails=1)
    _seed(tmp_path / "cand", search_fails=1, deploy_fails=1)
    code = main(["compare", "--baseline", str(tmp_path / "base"),
                 "--candidate", str(tmp_path / "cand"),
                 "--fail-on-new-modes"])
    assert code == 1
    assert "gate failed" in capsys.readouterr().err


def test_no_new_modes_passes_the_gate(tmp_path):
    _seed(tmp_path / "base", search_fails=1)
    _seed(tmp_path / "cand", search_fails=3)
    code = main(["compare", "--baseline", str(tmp_path / "base"),
                 "--candidate", str(tmp_path / "cand"),
                 "--fail-on-new-modes"])
    assert code == 0


def test_json_payload_carries_deltas(tmp_path, capsys):
    _seed(tmp_path / "base", n_ok=2)
    _seed(tmp_path / "cand", n_ok=4)
    code = main(["compare", "--baseline", str(tmp_path / "base"),
                 "--candidate", str(tmp_path / "cand"), "--json"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["baseline"]["traces"] == 2
    assert payload["candidate"]["traces"] == 4
    assert payload["tokens_delta"] == 200
    assert payload["new_modes"] == []


def test_prices_add_the_spend_row(tmp_path, capsys):
    _seed(tmp_path / "base", n_ok=1)
    _seed(tmp_path / "cand", n_ok=3)
    prices = tmp_path / "prices.json"
    prices.write_text(json.dumps({"gpt-x": 2.0}), encoding="utf-8")
    code = main(["compare", "--baseline", str(tmp_path / "base"),
                 "--candidate", str(tmp_path / "cand"),
                 "--prices", str(prices), "--json"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["spend"]["baseline"] == 0.2      # 100 tok @ $2/1k
    assert payload["spend"]["candidate"] == 0.6


def test_resolved_modes_are_named(tmp_path, capsys):
    _seed(tmp_path / "base", search_fails=1, deploy_fails=1)
    _seed(tmp_path / "cand", search_fails=1)
    code = main(["compare", "--baseline", str(tmp_path / "base"),
                 "--candidate", str(tmp_path / "cand")])
    assert code == 0
    assert "resolved modes" in capsys.readouterr().out
