"""v78: verify --all --strict / --quiet — policy gates for cron and CI.

Default batch semantics stay "nothing is broken" (unsigned records
pass with a note); strict mode enforces "every record must carry
verifiable evidence" and fails on unsigned/keyed-locked records too.
"""

import json

from approximately.cli import build_parser
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _mixed_store(tmp_path):
    store = TraceStore(str(tmp_path / "s"))
    with Recorder("signed run", store=store) as signed:
        signed.tool("bash", {"cmd": "ls"}, result="ok")
        signed.respond("done")
    bare = Recorder("unsigned run", save=False)
    bare.tool("bash", {"cmd": "pwd"}, result="/")
    bare.respond("done")
    (store.directory / f"{bare.trace.id}.json").write_text(
        json.dumps(bare.trace.to_dict()), encoding="utf-8")
    return store, signed.trace.id, bare.trace.id


def _run(tmp_path, *extra):
    store, _, _ = _mixed_store(tmp_path)
    parser = build_parser()
    args = parser.parse_args(["verify", "--all", "--store",
                              str(store.directory), *extra])
    return args.func(args), store


def test_default_batch_passes_unsigned(tmp_path, capsys):
    rc, _ = _run(tmp_path)
    assert rc == 0
    out = capsys.readouterr().out
    assert "unsigned" in out


def test_strict_fails_on_unsigned(tmp_path, capsys):
    rc, _ = _run(tmp_path, "--strict")
    assert rc == 1
    assert "[strict]" in capsys.readouterr().out


def test_quiet_suppresses_rows_but_keeps_summary(tmp_path, capsys):
    rc, _ = _run(tmp_path, "--quiet")
    assert rc == 0
    out = capsys.readouterr().out
    assert "intact" in out           # summary survives
    assert ": intact" not in out     # per-trace rows gone


def test_strict_json_marks_policy_and_exit(tmp_path, capsys):
    rc, _ = _run(tmp_path, "--strict", "--json")
    assert rc == 1
    body = json.loads(capsys.readouterr().out)
    assert body["strict"] is True
    assert body["summary"]["unsigned"] == 1
    assert body["summary"]["problem"] == 0  # nothing broken, policy only
