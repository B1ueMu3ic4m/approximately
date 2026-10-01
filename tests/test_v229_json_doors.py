"""v229: the JSON-door sweep — every --json parses, every time.

v221's tour caught export/import crashing on real argv; this round
sweeps the rest of the --json doors with a seeded store.  The
contract is narrow on purpose: each door exits 0 (or a documented
gate code) and prints *parseable JSON*.  Any future flag drift or
handler/argparse mismatch fails here instead of in someone's cron.
"""

import json

from approximately.cli import main
from approximately.exporter import export_store
from approximately.importer import import_file
from approximately.recorder import Recorder
from approximately.store import TraceStore

GATE_CODES = (0, 1)          # 1 = a documented "signal found" exit


def _seed(tmp_path):
    store = TraceStore(tmp_path / "s")
    bad = Recorder("checkout fails on discount", save=False)
    bad.tool("cart", {"sku": "X"}, result="added")
    bad.tool("search", {"q": "same"}, result="same")
    bad.tool("search", {"q": "same"}, result="same")
    bad.respond("gave up", success=False)
    store.save(bad.trace)
    good = Recorder("browse works", save=False)
    good.respond("done", success=True)
    store.save(good.trace)
    return store


def _run(capsys, *argv):
    code = main(list(argv))
    out = capsys.readouterr().out
    return code, out


def _json_door(capsys, *argv):
    code, out = _run(capsys, *argv)
    assert code in GATE_CODES, (argv, code, out[:200])
    payload = json.loads(out)          # must parse, whatever it says
    assert isinstance(payload, (dict, list))
    return payload


def test_analysis_doors(tmp_path, capsys):
    store = _seed(tmp_path)
    sid = str(store.directory)
    latest = "latest"
    for door in ("similar", "predict", "optimize", "counterfactual",
                 "repair", "context", "curve"):
        payload = _json_door(capsys, door, "--store", sid, latest,
                             "--json")
        assert payload is not None, door


def test_pair_doors(tmp_path, capsys):
    store = _seed(tmp_path)
    sid = str(store.directory)
    _run(capsys, "report", "--store", sid, "latest")
    # a success twin for diff/bisect: record one via the recorder
    good = Recorder("checkout fails on discount", save=False)
    good.tool("cart", {"sku": "X"}, result="added")
    good.respond("done", success=True)
    store.save(good.trace)
    ids = [t.id for t in store.list_traces()]
    for door in ("diff", "bisect"):
        payload = _json_door(capsys, door, "--store", sid,
                             ids[0], ids[1], "--json")
        assert payload is not None, door


def test_store_doors(tmp_path, capsys):
    store = _seed(tmp_path)
    sid = str(store.directory)
    for door, argv in (("dedupe", ()),
                       ("doctor", ()),
                       ("stats", ()),
                       ("query", ("success == false",))):
        payload = _json_door(capsys, door, "--store", sid, *argv,
                             "--json")
        assert payload is not None, door


def test_report_all_manifest_door(tmp_path, capsys):
    # report --json is --all's index manifest (documented), not a
    # stdout dump
    store = _seed(tmp_path)
    payload = _json_door(capsys, "report", "--store",
                         str(store.directory), "--all", "--json")
    assert payload is not None


def test_optimize_empty_is_honest_json(tmp_path, capsys):
    store = _seed(tmp_path)
    code, out = _run(capsys, "optimize", "--store",
                     str(store.directory), "latest", "--json")
    payload = json.loads(out)
    assert payload["optimized"] is False
    assert code == 1


def test_merge_door(tmp_path, capsys):
    store = _seed(tmp_path)
    other = _seed(tmp_path / "other")
    payload = _json_door(capsys, "merge", "--store",
                         str(store.directory), str(other.directory),
                         "--json")
    assert payload is not None


def test_scan_tool_door(tmp_path, capsys):
    tool_file = tmp_path / "tools.json"
    tool_file.write_text(json.dumps({
        "name": "search",
        "description": "search the web for flights",
    }), encoding="utf-8")
    code, out = _run(capsys, "scan-tool", str(tool_file), "--json")
    assert code in GATE_CODES
    json.loads(out)


def test_rotate_door(tmp_path, capsys):
    import os

    from approximately.integrity import sign

    store = _seed(tmp_path)
    key = os.urandom(32)
    for trace in store.list_traces():
        sign(trace, key=key)      # stamps the block into trace.meta
        store.save(trace)
    new_key_file = tmp_path / "new.key"
    new_key_file.write_bytes(os.urandom(32))
    payload = _json_door(capsys, "rotate", "--store",
                         str(store.directory),
                         "--new-key-file", str(new_key_file),
                         "--all", "--json")
    assert payload is not None


def test_verify_on_imported_trace_is_unsigned_not_tampered(tmp_path):
    # the semantic pin: a foreign OTLP trace has no evidence chain —
    # that is "unsigned", never "TAMPERED"
    store = _seed(tmp_path)
    outbox = tmp_path / "out"
    outbox.mkdir()
    export_store(store, outbox / "t.otlp.json", fmt="otel")
    back = TraceStore(tmp_path / "back")
    import_file(outbox / "t.otlp.json", back)
    from approximately.integrity import verify

    for trace in back.list_traces():
        result = verify(trace)
        assert result.verdict == "unsigned"


def test_fixture_doors(tmp_path, capsys):
    # the shipped benchmark corpus drives the last three doors:
    # benchmark, calibrate, convert-mast
    store = _seed(tmp_path)
    sid = str(store.directory)
    _ = sid
    out = tmp_path / "converted.json"
    for door, argv in (("benchmark", ("docs/mast-bench.jsonl",)),
                       ("calibrate", ("docs/mast-bench.jsonl",)),
                       ("convert-mast", ("docs/mast-bench.jsonl",
                                         str(out)))):
        code, out_text = _run(capsys, door, *argv, "--json")
        assert code in GATE_CODES, (door, out_text[:200])
        payload = json.loads(out_text)
        assert payload is not None, door
