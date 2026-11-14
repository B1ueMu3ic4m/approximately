"""v421: the analysis doors meet hostile datasets on their feet.

The conversion/dataset layer trusted its inputs: a MAST record
with a list where the options dict belonged crashed
``convert-mast`` with a traceback; one malformed line in a
benchmark corpus killed ``benchmark``/``bench-gate`` instead of
being named; a hand-edited trace with ``"tokens": 10**400`` or
``"created_at": "2024-01-01"`` waited in the store as a
TypeError for the next door that summed, sorted, or filtered;
and a foreign JSON's ``"id": "../../pwn"`` could ride an
analysis door into writing outside the store fence. This round
makes the boundary refuse by name, coerce, or clamp — never
crash, never silently skew.
"""

import json
import math
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from approximately.distill import _dataset_label, _dataset_record, load_dataset
from approximately.mastdata import _gold_modes, _success_of, _task_of, _to_trace
from approximately.store import TraceStore, safe_artifact
from approximately.trace import Trace, coerce_count, coerce_epoch

ROOT = Path(__file__).resolve().parent.parent


def _run(*args):
    return subprocess.run(
        [sys.executable, "-m", "approximately", *args],
        capture_output=True, text=True, cwd=str(ROOT))


def _store(tmp_path, **step_kw):
    from approximately.recorder import Recorder

    store = TraceStore(tmp_path)
    rec = Recorder("hardening task", store=store)
    rec.tool("sh", {"cmd": "ls"}, result="ok",
             **step_kw)
    rec.respond("done", success=True)
    store.save(rec.trace)
    return store, rec.trace


# ---- the trace boundary: one hostile JSONL line is coerced, not
# ---- a TypeError waiting in every downstream command

def test_tokens_never_overflow_the_math():
    assert coerce_count(10 ** 400) == 10_000_000, \
        "a 10**400-token line is a lie, capped not crashed"
    assert coerce_count("12ms") == 0
    assert coerce_count(None) == 0
    assert coerce_count(-5) == 0
    assert coerce_count(True) == 0, "bool is not a count"
    assert coerce_count(float("inf")) == 0
    assert coerce_count(1250) == 1250, "honest numbers survive"


def test_from_dict_coerces_a_hostile_step(tmp_path):
    raw = {"id": "abcd1234ef01", "task": "hostile",
           "created_at": "2024-01-01",
           "meta": None,
           "steps": [{"kind": "message", "tool": 5, "tokens": None,
                      "latency_ms": "12ms", "meta": None,
                      "args": [1, 2]}]}
    trace = Trace.from_dict(raw)
    assert trace.created_at == 0.0, \
        "a string epoch sorts oldest, it does not kill --since"
    assert trace.meta == {}
    step = trace.steps[0]
    assert step.tokens == 0 and step.latency_ms == 0
    assert step.tool == "5", "names are names, not sort bombs"
    assert step.meta == {} and step.args == {}


def test_infinite_epoch_is_refused_not_stored():
    assert coerce_epoch(float("inf")) == 0.0
    assert coerce_epoch(float("nan")) == 0.0
    assert coerce_epoch("2024-01-01") == 0.0


def test_the_store_survives_since_after_a_hostile_import(tmp_path):
    outside = tmp_path / "foreign.json"
    outside.write_text(json.dumps(
        {"id": "abcd1234ef01", "task": "foreign",
         "created_at": "2024-01-01",
         "steps": [{"kind": "tool_call", "tokens": 10 ** 400}]}),
        encoding="utf-8")
    store, _trace = _store(tmp_path / "s")
    store.directory.joinpath("abcd1234ef01.json").write_text(
        outside.read_text(encoding="utf-8"), encoding="utf-8")
    traces = store.list_traces(since_days=7)
    assert len(traces) == 2, (
        "--since survives the string epoch: no TypeError, both "
        "records readable (the zeroed one rides the file mtime)")


def test_cluster_survives_mixed_tool_types():
    from approximately.cluster import _cluster_key

    trace = Trace.from_dict({
        "id": "abcd1234ef01", "task": "mixed",
        "steps": [{"kind": "tool_call", "tool": 5},
                  {"kind": "tool_call", "tool": "sh"}]})
    key = _cluster_key(trace, "FM-1.3")
    assert isinstance(key[1], tuple),         "the sorted tool tuple survives a coerced int tool"


# ---- mastdata: hostile MAST records are excluded by rule

def test_a_list_where_options_belong_is_no_annotation():
    modes = _gold_modes({"note": {"options": ["Step repetition"]}})
    assert modes == [], "a hostile options is not a crash"
    assert _gold_modes({"note": {"options": "Step repetition"}}) == []


def test_hostile_subfields_become_defaults():
    assert _task_of({"problem_statement": 7}) == "(no statement)"
    assert _task_of({"problem_statement": "one line"}) != ""
    assert _success_of({"other_data": 5}) is None
    trace = _to_trace({"trajectory": 5})
    assert trace.steps == [], "a scalar trajectory is an empty run"
    trace = _to_trace({"trajectory": [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"}]})
    assert len(trace.steps) == 2, \
        "the message-dict schema still maps"


def test_convert_mast_door_answers_a_bad_output_by_name():
    src = Path(tempfile.mkdtemp())
    r = _run("convert-mast", str(src),
             str(src / "missing-dir" / "out.jsonl"))
    assert r.returncode == 2, r.stderr
    assert "error:" in r.stderr and "Traceback" not in r.stderr


# ---- distill: a poisoned corpus line is refused by line number

def test_a_malformed_line_is_named_with_its_number(tmp_path):
    ds = tmp_path / "ds.jsonl"
    good = {"task": "t", "steps": [], "label": "FM-1.3"}
    ds.write_text(json.dumps(good) + "\nnot json\n" + json.dumps(good),
                  encoding="utf-8")
    with pytest.raises(ValueError, match="dataset line 2"):
        load_dataset(ds)
    ds.write_text(json.dumps(good) + "\n[1, 2]\n", encoding="utf-8")
    with pytest.raises(ValueError, match="dataset line 2"):
        load_dataset(ds)


def test_an_unhashable_label_is_refused_by_name(tmp_path):
    ds = tmp_path / "ds.jsonl"
    ds.write_text(json.dumps({"task": "t", "steps": [],
                              "label": {"a": 1}}), encoding="utf-8")
    with pytest.raises(ValueError, match="gold label"):
        load_dataset(ds)
    with pytest.raises(ValueError, match="gold label"):
        _dataset_label({"label": 5}, 3)


def test_multi_label_lists_still_load(tmp_path):
    ds = tmp_path / "ds.jsonl"
    ds.write_text(json.dumps({"task": "t", "steps": [],
                              "labels": ["FM-1.3", "FM-2.1"]}),
                  encoding="utf-8")
    labeled = load_dataset(ds)
    assert len(labeled) == 1 and labeled[0][1] == ["FM-1.3", "FM-2.1"]


def test_the_corpus_helpers_refuse_by_line(tmp_path):
    with pytest.raises(ValueError, match="line 4"):
        _dataset_record("[1]", 4)
    with pytest.raises(ValueError, match="line 9"):
        _dataset_record("{oops", 9)


# ---- the exporter: NaN never ships, surrogates never crash

def test_nan_latency_cannot_poison_the_otlp_document(tmp_path):
    from approximately.exporter import _attr, _nanos

    assert _attr("x", float("nan")) is None, \
        "a strict OTLP parser rejects the doc over one NaN attr"
    assert _attr("x", float("inf")) is None
    assert _attr("x", 1.5) is not None
    assert _nanos(float("inf")) == "0", "inf cannot buy a ns stamp"
    _trace_store, trace = _store(tmp_path)
    trace.steps[0].latency_ms = float("nan")
    from approximately.exporter import export_otlp

    doc = export_otlp([trace], {})
    text = json.dumps(doc)  # strict parse of our own output
    assert "NaN" not in text


def test_a_surrogate_note_writes_and_reads_back(tmp_path):
    store, trace = _store(tmp_path)
    store.annotate(trace.id, "\ud800 poison")
    rows = store.annotations(trace.id)
    assert rows and rows[-1]["note"] == "\ud800 poison"
    from approximately.exporter import export_annotations

    side = tmp_path / "side.jsonl"
    export_annotations(store, side)
    back = json.loads(side.read_text(encoding="utf-8").splitlines()[0])
    assert back["note"] == "\ud800 poison"


# ---- the write fence: foreign ids do not name artifacts

def test_a_path_shaped_id_cannot_name_an_artifact(tmp_path):
    with pytest.raises(ValueError, match="safe filename"):
        safe_artifact(tmp_path, "../../pwn", ".report.html")
    with pytest.raises(ValueError, match="safe filename"):
        safe_artifact(tmp_path, "abc\n", ".curve.html")
    path = safe_artifact(tmp_path, "abcd1234ef01", ".report.html")
    assert path == tmp_path / "abcd1234ef01.report.html"


def test_the_report_door_refuses_a_foreign_id(tmp_path):
    foreign = tmp_path / "foreign.json"
    foreign.write_text(json.dumps(
        {"id": "../../pwn", "task": "escape", "steps": []}),
        encoding="utf-8")
    r = _run("--store", str(tmp_path / "s"), "report",
             str(foreign))
    assert r.returncode == 2, r.stderr
    assert "safe filename" in r.stderr
    assert "Traceback" not in r.stderr
    assert not (tmp_path / "pwn.report.html").exists(), \
        "no artifact outside the fence"


# ---- the doors answer instead of crashing

def test_the_benchmark_door_names_a_bad_corpus(tmp_path):
    ds = tmp_path / "ds.jsonl"
    ds.write_text('{"task": "t", "steps": []}\n{broken\n',
                  encoding="utf-8")
    r = _run("--store", str(tmp_path / "s"), "benchmark", str(ds))
    assert r.returncode == 2 and "dataset line 2" in r.stderr
    assert "Traceback" not in r.stderr


def test_curve_budgets_refuse_garbage_by_name(tmp_path):
    store, trace = _store(tmp_path / "s")
    r = _run("--store", str(store.directory), "curve", trace.id,
             "--budgets", "abc")
    assert r.returncode == 2 and "--budgets" in r.stderr
    r = _run("--store", str(store.directory), "curve", trace.id,
             "--budgets", "200,500")
    assert r.returncode == 0, r.stderr


def test_bench_gate_names_a_missing_dataset(tmp_path):
    from approximately.benchgate import run_gate

    code = run_gate(tmp_path / "absent.jsonl",
                    tmp_path / "floors.json", label="t")
    assert code == 1, "a missing dataset is a gate failure"


def test_native_import_caps_the_crafted_trace(tmp_path):
    store = TraceStore(tmp_path / "s")
    line = json.dumps({"id": "abcd1234ef01", "task": "flood",
                       "steps": [{"kind": "tool_call",
                                  "tool": "sh", "result": "x"}
                                 for _ in range(20_000)]})
    src = tmp_path / "flood.jsonl"
    src.write_text(line + "\n", encoding="utf-8")
    from approximately.importer import import_file

    result = import_file(src, store, fmt="native")
    stored = store.load(result["trace_ids"][0])
    assert len(stored.steps) == 10_000, \
        "a 200k-step line does not turn the store into the DoS"


def test_the_exporter_uses_the_counter_cap_not_the_lie(tmp_path):
    store = TraceStore(tmp_path / "s")
    line = json.dumps({"id": "abcd1234ef01", "task": "big",
                       "steps": [{"kind": "tool_call",
                                  "tokens": 10 ** 400}]})
    src = tmp_path / "big.jsonl"
    src.write_text(line + "\n", encoding="utf-8")
    from approximately.importer import import_file

    result = import_file(src, store, fmt="native")
    stored = store.load(result["trace_ids"][0])
    assert stored.steps[0].tokens == 10_000_000, \
        "the clamp matches the ingest cap"
    assert not math.isinf(float(stored.steps[0].tokens))
