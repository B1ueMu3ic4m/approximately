"""v560: the last corners answer by name.

The final-corners sweep found the few doors still trusting their
inputs: ``context --facts`` leaked a raw ``JSONDecodeError`` for a
malformed file and a traceback for a missing one, a JSON list (or
a prices.json-shaped table) rode in as "facts"; ``--budget 0``
crashed inside the runtime constructor. ``forecast_spend`` refused
a NaN ceiling at Budget construction but not its own — nan/inf
tripped ``math.ceil`` into ValueError/OverflowError mid-door
(three doors share that call: the status pulse, the fleet trend,
the nightly audit). The write-path corners: ``curve``/``distill``/
``benchmark --html`` wrote with bare ``write_text`` — an unwritable
parent crashed mid-door after the numbers were computed.
``convert-mast`` validated nothing before ``open(out, "w")``: a
typo'd checkout truncated the previous dataset and printed
"wrote <path>" with zero conversions — the destructive write
happened before the answer.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from approximately.forecast import forecast_spend

ROOT = Path(__file__).resolve().parent.parent


def _run(*args):
    return subprocess.run(
        [sys.executable, "-m", "approximately", *args],
        capture_output=True, text=True, cwd=str(ROOT))


def _stamp(tmp_path):
    from approximately.recorder import Recorder
    from approximately.store import TraceStore

    store = TraceStore(tmp_path / "s")
    rec = Recorder("corners task", store=store)
    rec.tool("sh", {"cmd": "ls"}, result="ok", tokens=500)
    rec.respond("done", success=True)
    store.save(rec.trace)
    return store, rec.trace


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


# ---- the context door: facts and budget answer by name

def test_a_missing_facts_file_is_a_refusal(tmp_path):
    store, trace = _stamp(tmp_path)
    r = _run("--store", str(store.directory), "context", trace.id,
             "--facts", str(tmp_path / "absent.json"))
    assert r.returncode == 2, (
        "a missing facts file used to traceback out of read_text")
    assert "error:" in r.stderr and "Traceback" not in r.stderr


def test_a_malformed_facts_file_is_a_refusal(tmp_path):
    store, trace = _stamp(tmp_path)
    bad = tmp_path / "bad.json"
    bad.write_text("{nope", encoding="utf-8")
    r = _run("--store", str(store.directory), "context", trace.id,
             "--facts", str(bad))
    assert r.returncode == 2, (
        "the raw JSONDecodeError used to leak out of the door")
    assert "Traceback" not in r.stderr


def test_a_list_of_facts_is_not_facts(tmp_path):
    store, trace = _stamp(tmp_path)
    rows = tmp_path / "rows.json"
    rows.write_text(json.dumps([["k", "v"]]), encoding="utf-8")
    r = _run("--store", str(store.directory), "context", trace.id,
             "--facts", str(rows))
    assert r.returncode == 2, (
        "a prices.json-shaped table rode in as facts: the needles "
        "must be strings, not whatever a list yields")
    assert "JSON object" in r.stderr


def test_a_non_positive_budget_is_a_refusal(tmp_path):
    store, trace = _stamp(tmp_path)
    for bad in ("0", "-5"):
        r = _run("--store", str(store.directory), "context",
                 trace.id, "--budget", bad)
        assert r.returncode == 2, (
            f"--budget {bad} crashed inside the runtime constructor")
        assert "budget must be positive" in r.stderr


# ---- the spend ceiling: nan/inf is refused by name, three doors

def test_a_non_finite_ceiling_is_refused_at_the_source():
    days = [{"day": "2026-10-01", "est_spend": 5.0},
            {"day": "2026-10-02", "est_spend": 6.0}]
    with pytest.raises(ValueError, match="finite"):
        forecast_spend(days, ceiling=float("nan"))
    with pytest.raises(ValueError, match="finite"):
        forecast_spend(days, ceiling=float("inf"))


def test_the_status_pulse_answers_a_nan_ceiling(tmp_path):
    store, _trace = _stamp(tmp_path)
    digest = _digest(tmp_path, [5.0, 15.0])
    r = _run("--store", str(store.directory), "status",
             "--digest-dir", str(digest), "--spend-ceiling", "nan")
    assert r.returncode == 2, (
        "math.ceil(nan) used to ValueError out of the status door")
    assert "finite" in r.stderr and "Traceback" not in r.stderr


def test_the_fleet_trend_answers_a_nan_ceiling(tmp_path):
    _stamp(tmp_path)
    digest = _digest(tmp_path, [5.0, 15.0])
    r = _run("fleet", str(tmp_path / "s"), "--trend",
             "--digest-dir", str(digest), "--spend-ceiling", "nan")
    assert r.returncode == 2, (
        "the trend door used to die mid-summary on a nan ceiling")
    assert "finite" in r.stderr and "Traceback" not in r.stderr


def test_the_audit_door_fails_the_ceiling_check_by_name(tmp_path):
    store, _trace = _stamp(tmp_path)
    digest = _digest(tmp_path, [5.0, 15.0])
    r = _run("--store", str(store.directory), "audit",
             "--digest-dir", str(digest), "--spend-ceiling", "nan")
    assert r.returncode == 1, (
        "the audit used to die mid-section: a broken ceiling is a "
        "failed check, not a crash")
    assert "finite" in r.stdout
    r2 = _run("--store", str(store.directory), "audit",
              "--digest-dir", str(digest), "--spend-ceiling", "100.0")
    assert r2.returncode == 0, "an honest ceiling still passes"


# ---- the write corners: an unwritable path answers by name

def test_curve_answers_an_unwritable_output(tmp_path):
    store, trace = _stamp(tmp_path)
    out = tmp_path / "missing-dir" / "curve.html"
    r = _run("--store", str(store.directory), "curve", trace.id,
             "--budgets", "200,500", "--output", str(out))
    assert r.returncode == 2, (
        "the bare write_text used to FileNotFoundError mid-door")
    assert "error:" in r.stderr and "Traceback" not in r.stderr


def test_distill_answers_an_unwritable_output(tmp_path):
    store, _trace = _stamp(tmp_path)
    out = tmp_path / "missing-dir" / "sft.jsonl"
    r = _run("--store", str(store.directory), "distill",
             "--output", str(out))
    assert r.returncode == 2, (
        "export_sft used to crash after the numbers were computed")
    assert "error:" in r.stderr and "Traceback" not in r.stderr


def test_benchmark_answers_an_unwritable_html(tmp_path):
    ds = tmp_path / "ds.jsonl"
    ds.write_text(json.dumps({"task": "deploy the service",
                              "steps": [], "label": "FM-1.3"}) + "\n",
                  encoding="utf-8")
    out = tmp_path / "missing-dir" / "board.html"
    r = _run("--store", str(tmp_path / "s"), "benchmark", str(ds),
             "--html", str(out))
    assert r.returncode == 2, (
        "the leaderboard write used to FileNotFoundError after the "
        "scores were computed")
    assert "error:" in r.stderr and "Traceback" not in r.stderr


# ---- convert-mast: the source is validated before the output dies

def _mast_record(tmp_path, src):
    src.mkdir(parents=True, exist_ok=True)
    (src / "a.json").write_text(json.dumps({
        "task_id": "m1", "problem_statement": "do the thing",
        "trajectory": [{"role": "user", "content": "hi"},
                       {"role": "assistant", "content": "hello"}],
        "note": {"options": {"Step repetition": "yes"}},
        "other_data": {}}), encoding="utf-8")
    return src


def test_a_missing_checkout_cannot_truncate_the_dataset(tmp_path):
    out = tmp_path / "out.jsonl"
    out.write_text("previous dataset\n", encoding="utf-8")
    r = _run("convert-mast", str(tmp_path / "typo-checkout"),
             str(out))
    assert r.returncode == 2, (
        "the old door truncated the previous dataset and printed "
        "'wrote <path>' with zero conversions")
    assert "not found" in r.stderr
    assert out.read_text(encoding="utf-8") == "previous dataset\n", \
        "the destructive write happened before the answer"


def test_a_file_source_keeps_its_old_converted_zero_semantics(tmp_path):
    src = tmp_path / "loose.json"
    src.write_text("{}\n", encoding="utf-8")
    r = _run("convert-mast", str(src), str(tmp_path / "out.jsonl"))
    assert r.returncode == 1, (
        "a file source never matched rglob('*.json'); it converts 0 "
        "and says so, it does not become a missing-source refusal")
    assert "converted 0" in r.stdout
