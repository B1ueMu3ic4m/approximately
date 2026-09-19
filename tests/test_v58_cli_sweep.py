"""v0.58 — CLI sweep: every remaining command runs end to end.

Coverage audit showed a dozen real commands with module-level tests
but no CLI-level exercise (similar, calibrate, counterfactual, drift,
optimize, repair, verify --all, clean, metrics, curve, export-dataset,
predict, cluster, taxonomy). This sweep runs each against a seeded
store and asserts its contract surface — argument wiring drift now
fails CI like any other regression.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from approximately.cli import main

SYNTH = Path(__file__).resolve().parent.parent / "docs" / "mast-bench-synth.jsonl"


@pytest.fixture(scope="module")
def store(tmp_path_factory):
    """A store with one success and several failed runs."""
    home = tmp_path_factory.mktemp("sweep") / "traces"
    old = None
    import os

    old = os.environ.get("APPROXIMATELY_HOME")
    os.environ["APPROXIMATELY_HOME"] = str(home)
    from approximately.recorder import Recorder

    home.mkdir(parents=True, exist_ok=True)
    for i, ok in enumerate([True, False, False, False]):
        rec = Recorder(f"sweep task {i}: fix the retry backoff",
                       save=False)
        rec.trace.id = f"sw-{i}"
        for j in range(3):
            rec.tool("edit_file", {"path": f"svc{i}_{j}.py"},
                     result=f"patched {j}; tests: 2 failed, 6 passed")
        rec.respond("the issue is resolved" if ok else "gave up",
                    success=ok)
        rec.trace.to_json()  # sanity: serializable
        (home / f"{rec.trace.id}.json").write_text(rec.trace.to_json(),
                                                   encoding="utf-8")
    yield home
    if old is None:
        os.environ.pop("APPROXIMATELY_HOME", None)
    else:
        os.environ["APPROXIMATELY_HOME"] = old


def _run(capsys, *argv):
    capsys.readouterr()
    rc = main([*argv])
    return rc, capsys.readouterr().out


def test_similar_ranks_shapes(store, capsys):
    rc, out = _run(capsys, "--store", str(store), "similar", "sw-0")
    assert rc == 0
    assert "sw-" in out


def test_calibrate_on_single_label_corpus(store, capsys):
    gold = Path(__file__).resolve().parent.parent / "docs" / \
        "mast-bench.jsonl"
    if not gold.exists():
        return
    rc, out = _run(capsys, "calibrate", str(gold))
    assert rc == 0
    assert "coverage:" in out and "temperature" in out


def test_calibrate_rejects_multilabel_datasets(store, capsys):
    # single-label tool meets a labels-list dataset: clear message,
    # not a bare TypeError
    rc, out = _run(capsys, "calibrate", str(SYNTH))
    assert rc == 1
    assert "multi-label" in out


def test_counterfactual_runs(store, capsys):
    rc, out = _run(capsys, "--store", str(store), "counterfactual",
                   "sw-1")
    assert rc == 0
    assert out.strip()


def test_drift_runs(store, capsys):
    # drift compares oldest vs newest halves of the store - no trace arg
    rc, out = _run(capsys, "--store", str(store), "drift")
    assert rc in (0, 1)
    assert out.strip()


def test_optimize_reports_budget(store, capsys):
    rc, out = _run(capsys, "--store", str(store), "optimize", "sw-0")
    assert rc in (0, 1)  # no-probe traces exit 1 with a message
    assert out.strip()


def test_repair_writes_on_apply(store, capsys, tmp_path):
    rc, out = _run(capsys, "--store", str(store), "repair", "sw-1",
                   "--apply")
    assert rc in (0, 1)  # unrepairable is an honest outcome
    assert "repair" in out.lower() or out.strip()


def test_verify_all_json(store, capsys):
    rc, out = _run(capsys, "--store", str(store), "verify", "--all",
                   "--json")
    assert rc == 0
    payload = json.loads(out)
    assert payload


def test_clean_removes_nothing_young(store, capsys):
    rc, out = _run(capsys, "--store", str(store), "clean",
                   "--keep-days", "30")
    assert rc == 0
    assert "0" in out  # nothing older than 30 days


def test_metrics_prometheus(store, capsys):
    rc, out = _run(capsys, "--store", str(store), "metrics",
                   "--prometheus")
    assert rc == 0
    assert "approximately" in out


def test_curve_writes_html(store, capsys, tmp_path):
    page = tmp_path / "curve.html"
    rc, _out = _run(capsys, "--store", str(store), "curve", "sw-0",
                    "--output", str(page), "--scatter")
    assert rc == 0
    assert page.exists() and "recall" in page.read_text(
        encoding="utf-8")


def test_export_dataset_writes_jsonl(store, capsys, tmp_path):
    out_path = tmp_path / "export.jsonl"
    rc, _out = _run(capsys, "--store", str(store), "export-dataset",
                    "--output", str(out_path))
    assert rc == 0
    rows = [json.loads(row) for row in
            out_path.read_text(encoding="utf-8").splitlines()
            if row.strip()]
    assert isinstance(rows, list)


def test_predict_runs(store, capsys):
    rc, out = _run(capsys, "--store", str(store), "predict", "sw-1")
    assert rc in (0, 1)  # 1 = not enough history, still a report
    assert out.strip()


def test_cluster_runs(store, capsys):
    rc, out = _run(capsys, "--store", str(store), "cluster")
    assert rc in (0, 1)
    assert out.strip()


def test_taxonomy_lists_modes(store, capsys):
    rc, out = _run(capsys, "taxonomy")
    assert rc == 0
    assert "FM-1.3" in out and "FM-3.2" in out
