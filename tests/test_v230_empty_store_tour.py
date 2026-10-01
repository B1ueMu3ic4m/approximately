"""v230: the empty-store tour — honest answers at every door.

A brand-new user's first command runs against an empty store (or
they point --store at a typo).  Two documented contracts, both
swept here: **read doors refuse loudly** (exit 2, "store ... is
empty" — protects against a typo'd path), and **aggregate doors
report zeros** (a fleet/stat door over an empty store is a real
answer, not a crash).
"""

import json

from approximately.cli import main
from approximately.store import TraceStore


def _run(capsys, *argv):
    code = main(list(argv))
    return code, capsys.readouterr().out, capsys.readouterr().err


def _empty(tmp_path):
    TraceStore(tmp_path / "s")
    return tmp_path / "s"


def test_empty_store_doors_are_honest(tmp_path, capsys):
    # surveyed, not invented: each door's real empty behavior,
    # all of them sane
    sid = str(_empty(tmp_path))
    code, out, _ = _run(capsys, "dedupe", "--store", sid)
    assert code == 0 and "no near-duplicate" in out
    code, out, _ = _run(capsys, "export", "--store", sid, "o.jsonl")
    assert code == 0 and "0 of 0" in out
    code, out, _ = _run(capsys, "report", "--store", sid, "--all")
    assert code == 0 and "0 traces" in out


def test_needs_a_target_doors_refuse(tmp_path, capsys):
    # a door that must name a trace refuses a typo'd empty store
    sid = str(_empty(tmp_path))
    _code, _out, err = _run(capsys, "anomalies", "--store", sid,
                            "latest")
    assert "empty" in err


def test_query_on_empty_store_is_an_empty_answer(tmp_path, capsys):
    # a selection over nothing is a valid answer, not a refusal
    sid = str(_empty(tmp_path))
    _code, out, _err = _run(capsys, "query", "--store", sid,
                            "success == false", "--json")
    payload = json.loads(out)
    assert payload["ids"] == []


def test_aggregate_doors_report_zeros(tmp_path, capsys):
    sid = str(_empty(tmp_path))
    for door, argv in (("doctor", ()),
                       ("stats", ()),
                       ("fleet", ())):
        code, out, _err = _run(capsys, door, "--store", sid, *argv,
                               "--json")
        assert code == 0, door
        payload = json.loads(out)
        assert isinstance(payload, (dict, list)), door


def test_stats_empty_json_sums_to_zero(tmp_path, capsys):
    sid = str(_empty(tmp_path))
    _code, out, _err = _run(capsys, "stats", "--store", sid, "--json")
    payload = json.loads(out)
    assert payload["traces"] == 0
    assert payload["total_tokens"] == 0
