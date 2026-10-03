"""Night VI, round 9: fuzz 20 — the new surfaces under adversarial input.

Probes that found real gaps, now pins: a negative price paid the run
to burn (usd went to -1,500 while the ceiling sat silent), negative
tokens ran the meter backwards, and float token counts drifted the
meters.  Prices must be finite and non-negative; token counts must
be non-negative ints.
"""

import json

import pytest

from approximately.budget import Budget
from approximately.doctor import QUARANTINE_DIR, doctor, quarantine_corrupt
from approximately.recorder import Recorder
from approximately.store import TraceStore


def test_negative_price_is_refused_not_pocketed():
    with pytest.raises(ValueError, match="finite non-negative"):
        Budget(usd=1.0, prices={"m": -0.5})


def test_nan_and_infinite_prices_are_refused():
    with pytest.raises(ValueError, match="finite"):
        Budget(usd=1.0, prices={"m": float("nan")})
    with pytest.raises(ValueError, match="finite"):
        Budget(usd=1.0, prices={"m": float("inf")})


def test_negative_tokens_cannot_un_burn():
    b = Budget(tokens=100)
    b.charge(tokens=500)
    with pytest.raises(ValueError, match="non-negative int"):
        b.charge(tokens=-400)
    assert b.tokens == 500  # the meter never ran backwards
    assert b.exceeded_reasons() == ["tokens"]


def test_float_and_bool_tokens_are_refused():
    b = Budget(tokens=100)
    with pytest.raises(ValueError, match="non-negative int"):
        b.charge(tokens=50.5)
    with pytest.raises(ValueError, match="non-negative int"):
        b.charge(tokens=True)
    assert b.tokens == 0


def test_recorder_surfaces_the_refusal_at_the_step():
    budget = Budget(tokens=100)
    with pytest.raises(ValueError, match="non-negative int"), \
            Recorder("bad meter", model="m", save=False,
                     budget=budget) as rec:
        rec.tool("a", tokens=10)
        rec.tool("b", tokens=-5)
    # the honest step is still on the record
    assert [s.tokens for s in rec.trace.steps if s.kind == "tool_call"] \
        == [10]


def test_billion_token_burn_stays_exact():
    b = Budget(tokens=10 ** 15)
    b.charge(tokens=10 ** 9)
    b.charge(tokens=10 ** 9)
    assert b.tokens == 2 * 10 ** 9
    assert b.exceeded_reasons() == []


def test_fuzz_token_streams_match_a_plain_sum():
    import random
    rng = random.Random(20261003)
    b = Budget(tokens=10 ** 9)
    total = 0
    for _ in range(500):
        n = rng.randrange(0, 10_000)
        b.charge(tokens=n)
        total += n
        assert b.tokens == total
    assert b.exceeded_reasons() == ([] if total <= 10 ** 9
                                    else ["tokens"])


def test_quarantine_manifest_survives_hostile_error_text(tmp_path):
    store = TraceStore(tmp_path)
    with Recorder("good", model="m/1", store=store) as rec:
        rec.respond("done", success=True)
    weird = tmp_path / "wëird 名字 with \"quotes\".json"
    weird.write_text('{"steps": [1e999]}', encoding="utf-8")
    report = doctor(tmp_path)
    assert "wëird 名字 with \"quotes\".json" in report.corrupt
    assert quarantine_corrupt(tmp_path, report) == \
        [weird.name]
    line = (tmp_path / QUARANTINE_DIR / "manifest.jsonl"
            ).read_text(encoding="utf-8").splitlines()[0]
    entry = json.loads(line)  # round-trips no matter the error text
    assert entry["file"] == weird.name


def test_quarantine_many_clashes_all_preserved(tmp_path):
    qdir = tmp_path / QUARANTINE_DIR
    qdir.mkdir()
    for n in range(4):
        (qdir / "dup.json").write_text(f"q{n}", encoding="utf-8")
        (tmp_path / "dup.json").write_text(f"store{n}", encoding="utf-8")
        report = doctor(tmp_path)
        assert quarantine_corrupt(tmp_path, report) == ["dup.json"]
    kept = sorted(p.read_text(encoding="utf-8")
                  for p in qdir.glob("dup.json*"))
    # each pass overwrites the unsuffixed name (q0..q3) and moves the
    # store's file to the next free suffix — nothing is ever lost
    assert kept == ["q3", "store0", "store1", "store2", "store3"]
    assert len((qdir / "manifest.jsonl")
               .read_text(encoding="utf-8").splitlines()) == 4


def test_junit_payload_survives_pathological_names(tmp_path, capsys):
    import argparse
    import xml.etree.ElementTree as ET

    from approximately.cli import cmd_ci
    store = TraceStore(tmp_path)
    with Recorder('task "quotes" & <angles>', model="m/1",
                  store=store) as rec:
        rec.tool("t", tokens=1)
        rec.respond("done", success=False)
    args = argparse.Namespace(store=str(tmp_path), format="junit",
                              json=False, prices=None, min_traces=None,
                              since=None, max_failure_rate=0.5)
    assert cmd_ci(args) == 1
    root = ET.fromstring(capsys.readouterr().out)  # parses clean
    assert root.find("testsuite").get("failures") == "1"
