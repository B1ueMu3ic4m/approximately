"""v430: the money meter tells the truth, the destructive doors
answer before they destroy.

The recon audit of the money/ops layer found the breaker
decorative exactly when it mattered most: per-charge rounding
dropped every sub-$0.00005 charge forever (20k per-token charges
read $0.00 against a true $0.10), a provider-prefixed model name
(``openai/gpt-4o`` vs a ``gpt-4o`` catalog) silently disarmed
the dollar meter into ``unpriced_tokens``, and a NaN ceiling
compared false against every spend. The destructive doors had
their own teeth: ``clean --keep-days 0`` deleted the whole
store (breach evidence included) with one flag, retention
``--apply`` unlinked files that had become unreadable between
plan and apply (``poison is never touched`` was the plan's own
promise), and the dedupe scan truncated to its cap without
counting the loss while every dataset door printed
``dropped 0 near-duplicate(s)``. The redact door's
``--replacement`` was a re.sub template — ``\\g<0>`` pasted the
secret back in and still reported scrubbed.
"""

import subprocess
import sys
import tempfile
import time
from pathlib import Path

from approximately.align import dedupe_traces
from approximately.budget import Budget
from approximately.redact import compile_patterns, redact_text
from approximately.retention import apply_plan, retention_plan
from approximately.store import TraceStore
from approximately.trace import Trace, _coerce_success

ROOT = Path(__file__).resolve().parent.parent


def _run(*args):
    return subprocess.run(
        [sys.executable, "-m", "approximately", *args],
        capture_output=True, text=True, cwd=str(ROOT))


# ---- the meter: true spend, honest rates, ceilings that trip

def test_sub_cent_charges_accumulate_to_the_ceiling():
    b = Budget(usd=0.05, prices={"m": 0.0005})
    for _ in range(20_000):
        b.charge(10, model="m")
    assert b.usd >= 0.05,  (
        "20k x $0.00005 is $0.10: the per-charge rounding  "
        "dropped every charge forever and the breaker never tripped")
    assert "usd" in b.exceeded_reasons()
    assert b.state["usd"] == 0.1, "the snapshot still rounds"


def test_a_provider_prefixed_model_charges_its_rate():
    b = Budget(usd=1.0, prices={"gpt-4o": 0.0025})
    b.charge(1_000_000, model="openai/gpt-4o")
    assert b.usd == 2.5,  (
        "a key mismatch used to disarm the meter into  "
        "unpriced_tokens while the run burned")
    assert b.unpriced_tokens == 0


def test_case_insensitive_and_exact_rates_agree():
    b = Budget(usd=10.0, prices={"GPT-4o": 0.03})
    b.charge(1000, model="gpt-4o")
    assert b.usd == 0.03
    assert b._rate_for("gpt-4o") == 0.03
    assert b._rate_for("openai/gpt-4o") == 0.03
    assert b._rate_for("unknown-model") is None, \
        "unknown stays unpriced, never silently zero"


def test_a_nan_ceiling_is_refused_not_decorative():
    with pytest.raises(ValueError, match="finite"):
        Budget(usd=float("nan"), prices={"m": 1.0})
    with pytest.raises(ValueError, match="finite"):
        Budget(usd=float("inf"), prices={"m": 1.0})
    with pytest.raises(ValueError, match="finite"):
        Budget(tokens=float("nan"))


def test_honest_ceilings_still_trip():
    b = Budget(usd=1.0, prices={"m": 1.0})
    b.charge(1_500_000, model="m")
    assert b.exceeded_reasons() == ["usd"]
    b2 = Budget(tokens=100)
    b2.charge(150)
    assert b2.exceeded_reasons() == ["tokens"]


# ---- the destructive doors answer before they destroy

def _store_with(tmp_path, n=3, breach=False, age_days=None):
    from approximately.recorder import Recorder

    store = TraceStore(tmp_path)
    ids = []
    for i in range(n):
        rec = Recorder(f"ops task {i}", store=store)
        rec.tool("sh", {"cmd": "x"}, result="ok")
        rec.respond("done", success=(not breach))
        if age_days is not None:
            # the retention clock reads created_at: the fixture's
            # age is the fixture's to set (v3.82's lesson)
            rec.trace.created_at = (
                time.time() - age_days * 86400.0)
            store.save(rec.trace, stamp=False)
        else:
            store.save(rec.trace)
        ids.append(rec.trace.id)
    return store, ids


def test_clean_keep_days_zero_is_a_refusal(capsys):
    import argparse

    from approximately.cli import cmd_clean

    store, _ids = _store_with(Path(tempfile.mkdtemp()))
    args = argparse.Namespace(store=str(store.directory),
                              keep_days=0, json=False)
    code = cmd_clean(args)
    err = capsys.readouterr().err
    assert code == 2, "keep-days 0 is rm -rf's job"
    assert "--keep-days" in err and "breach evidence" in err


def test_retention_apply_keeps_a_poison_file(tmp_path):
    store, ids = _store_with(tmp_path, n=2, age_days=90)
    plan = retention_plan(store, keep_days=1)
    assert plan["retire"], "the plan wants them all retired"
    # one file tears between plan and apply: unreadable = keep
    victim = store.directory / f"{ids[0]}.json"
    victim.write_text("{corrupt", encoding="utf-8")
    removed = apply_plan(store, plan)
    assert removed == 1, \
        "the readable one retires; the torn one is kept"
    assert victim.exists(), \
        "'poison is never touched' is the plan's own promise"


def test_retention_apply_survives_a_vanished_file(tmp_path):
    store, ids = _store_with(tmp_path, n=2, age_days=90)
    plan = retention_plan(store, keep_days=1)
    (store.directory / f"{ids[0]}.json").unlink()
    removed = apply_plan(store, plan)
    assert removed == 1,  (
        "a file that vanished between plan and apply is done,  "
        "not a FileNotFoundError mid-delete")


def test_dedupe_counts_its_truncation():
    store, _ids = _store_with(Path(tempfile.mkdtemp()), n=30)
    traces = store.list_traces()
    kept, dropped, capped = dedupe_traces(traces, max_traces=10)
    assert len(kept) + dropped + capped == len(traces), \
        "the conservation law: nothing leaves uncounted"
    assert capped == 20, \
        "20 traces used to vanish with 'dropped 0' on the print"


def test_export_names_the_cap_in_its_json(tmp_path,
                                          monkeypatch):
    from approximately import align
    from approximately.exporter import export_store

    store, _ids = _store_with(tmp_path, n=25)
    out = tmp_path / "out.jsonl"

    real = align.dedupe_traces

    def capped_dedupe(traces, **kw):
        kept, dropped, _capped = real(traces, **kw)
        # pretend the scan cap bit: 15 traces left out
        return kept, dropped, 15

    monkeypatch.setattr(align, "dedupe_traces", capped_dedupe)
    result = export_store(store, out, dedupe=True)
    assert result["dedupe_capped"] == 15,  (
        "the export JSON carries the cap: a dataset door  "
        "cannot silently lose traces")


# ---- the share copy: the replacement is literal, the split is strict

def test_replacement_backslashes_are_literal_not_templates():
    table = compile_patterns(extra=["secret=password\\S+"])
    text, report = redact_text("password=hunter2secret", table)
    assert "hunter2secret" not in text,  (
        "\\g<0> used to paste the whole match - the secret  "
        "survived and the report still said scrubbed")
    assert sum(report.values()) == 1, "the hit is still counted"


def test_a_bare_regex_with_equals_stays_whole():
    table = compile_patterns(
        extra=["(?i)password=\\S+"])
    custom = [(n, p) for n, p in table.items()
              if n.startswith("custom-")]
    assert custom, "the bare regex landed as its own entry"
    _name, pattern = custom[0]
    assert pattern.search("Password=xyz"), \
        "the '=' inside the regex is data, not a name separator"
    text, report = redact_text(
        "harmless meeting notes about turtles", table)
    assert "harmless" in text and sum(report.values()) == 0,  (
        "the old split turned this pattern into '.*' and  "
        "redacted the whole document under a garbage name")


def test_named_patterns_still_split():
    table = compile_patterns(extra=["token=sk-[a-z]+"])
    assert "token" in table, "a real name=regex still parses"
    assert table["token"].search("sk-abc")


# ---- the boundary: success and index join the coercion family

def test_success_is_a_verdict_not_a_truthy_lie():
    assert _coerce_success(False) is False
    assert _coerce_success("false") is False, \
        "a string false used to retire failure evidence early"
    assert _coerce_success(0) is False
    assert _coerce_success(1) is True
    assert _coerce_success("TRUE") is True
    assert _coerce_success("no") is None, \
        "an unverdicted record is unknown, not a success"
    assert _coerce_success(None) is None


def test_a_string_false_failure_stores_as_false(tmp_path):
    store = TraceStore(tmp_path)
    foreign = Trace.from_dict({"id": "abcd1234ef01",
                               "task": "foreign", "success": "false",
                               "steps": []})
    store.save(foreign)
    loaded = store.load("abcd1234ef01")
    assert loaded.success is False, (
        "the truthy string 'false' used to ride the success "
        "clock: retention retired failure evidence early and "
        "the stats undercounted failures")
    plan = retention_plan(store, keep_days=1, failure_days=30)
    # age policy still picks the candidates (zeroed epoch is old);
    # the clock choice is what the coercion fixes
    verdicts = {row["id"] for row in plan["retire"]}
    assert "abcd1234ef01" in verdicts or \
        plan["kept"].get("failure_young"), \
        "the verdict, not a truthy string, picks the clock"


def test_hostile_step_index_cannot_crash_the_budget_door(tmp_path):
    store = TraceStore(tmp_path)
    trace = Trace.from_dict({"id": "abcd1234ef01", "task": "hostile",
                             "steps": [{"kind": "tool_call",
                                        "index": 0},
                                       {"kind": "tool_call",
                                        "index": "one"}]})
    store.save(trace)
    r = _run("--store", str(store.directory), "budget", "abcd1234ef01",
             "--tokens", "10")
    assert "Traceback" not in r.stderr, \
        "the mixed-type indexes used to TypeError the comparator"
    assert r.returncode == 0, r.stderr


def test_the_budget_door_names_a_corrupt_trace(tmp_path):
    store, _ids = _store_with(tmp_path, n=1)
    (store.directory / "corrupt01ab.json").write_text(
        "{corrupt", encoding="utf-8")
    r = _run("--store", str(store.directory), "budget", "corrupt01ab",
             "--tokens", "10")
    assert r.returncode == 2 and "cannot load trace" in r.stderr
    assert "Traceback" not in r.stderr


def test_the_redact_door_names_a_corrupt_trace(tmp_path):
    store, _ids = _store_with(tmp_path, n=1)
    (store.directory / "corrupt01ab.json").write_text(
        "{corrupt", encoding="utf-8")
    r = _run("--store", str(store.directory), "redact", "corrupt01ab")
    assert r.returncode == 2 and "cannot load trace" in r.stderr


def test_clean_survives_a_vanished_file(tmp_path):
    import argparse
    import time as _t

    from approximately.cli import cmd_clean

    store, ids = _store_with(tmp_path, n=2)
    victim = store.directory / f"{ids[0]}.json"
    old = _t.time() - 90 * 86400
    import os

    os.utime(victim, (old, old))
    victim.unlink()
    args = argparse.Namespace(store=str(store.directory),
                              keep_days=30, json=True)
    code = cmd_clean(args)
    assert code == 0,  (
        "a file that vanishes mid-pass is nothing to age,  "
        "nothing to crash on")


def test_the_tail_watch_clamps_a_negative_interval(tmp_path):
    store, _ids = _store_with(tmp_path, n=1)
    r = _run("--store", str(store.directory), "tail",
             "--interval", "-5", "--max-passes", "1")
    assert "sleep length must be non-negative" not in r.stderr, \
        "the watch loop survives a bad interval config"


import pytest
