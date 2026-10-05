"""v293: the redaction door — sanitized share-copies.

Traces are shared: pasted into issues, attached to postmortems. The
``redact`` door produces a copy with secret-shaped matches scrubbed,
a fresh id and a fresh chain, while the original file stays
byte-for-byte untouched. Provenance (source id, per-pattern hits)
rides in ``meta["redacted"]``.
"""

import argparse
import json

import pytest

from approximately.cli import cmd_redact
from approximately.integrity import verify
from approximately.redact import BUILTIN_PATTERNS, compile_patterns, redact_trace
from approximately.store import TraceStore
from approximately.trace import Step, Trace

SECRET = "sk-abcdefghijklmnopqrst"
AWS = "AKIAIOSFODNN7EXAMPLE"


def _trace() -> Trace:
    t = Trace(task="rotate leaked key now", model="m")
    t.add(Step(kind="tool_call", tool="http",
               args={"headers": {"Authorization": "Bearer abcdef1234567890ab"},
                     "note": "clean"},
               result=f"called with {AWS} and {SECRET}"))
    t.add(Step(kind="response", result="done", tokens=7))
    return t


def test_builtins_catch_the_curated_shapes():
    share, report = redact_trace(_trace())
    assert report["hits"]["aws_key"] == 1
    assert report["hits"]["openai_key"] == 1
    assert report["hits"]["bearer"] == 1
    blob = json.dumps(share.to_dict())
    assert AWS not in blob
    assert SECRET not in blob


def test_every_builtin_fires_on_its_own_fixture():
    from approximately.redact import _scrub

    fixtures = {
        "aws_key": "x AKIAIOSFODNN7EXAMPLE y",
        "gcp_key": "x AIza" + "A" * 35 + " y",
        "github_token": "x ghp_" + "A" * 36 + " y",
        "openai_key": "x sk-" + "a" * 20 + " y",
        "slack_token": "x xoxb-" + "a" * 12 + " y",
        "jwt": "x eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0."
               "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJVadQssw5c y",
        "bearer": "Authorization: Bearer abcdef1234567890ab",
        "private_key": "-----BEGIN RSA PRIVATE KEY-----\nabc\n"
                       "-----END RSA PRIVATE KEY-----",
    }
    assert set(fixtures) == set(BUILTIN_PATTERNS)
    for name, blob in fixtures.items():
        table = compile_patterns(only=[name])
        hits: dict = {}
        scrubbed = _scrub(blob, table, hits)
        assert hits.get(name) == 1, name
        assert f"[REDACTED:{name}]" in scrubbed


def test_share_copy_is_a_copy():
    t = _trace()
    share, report = redact_trace(t)
    assert share.id != t.id
    assert report["source"] == t.id
    assert report["share_id"] == share.id
    assert report["hits"]["aws_key"] == 1
    assert report["hits"]["openai_key"] == 1
    assert report["hits"]["bearer"] == 1
    # original byte-identical in memory
    assert AWS in t.steps[0].result
    assert SECRET in t.steps[0].result
    assert "Bearer abcdef1234567890ab" in \
        t.steps[0].args["headers"]["Authorization"]
    # copy is clean, nested args included
    blob = json.dumps(share.to_dict())
    assert AWS not in blob and SECRET not in blob
    assert "[REDACTED:aws_key]" in blob
    assert share.steps[0].args["headers"]["Authorization"] == \
        "[REDACTED:bearer]"
    assert share.steps[0].args["note"] == "clean"
    assert share.task == t.task  # no secret in task survives unchanged
    assert share.meta["redacted"]["from"] == t.id
    assert share.meta["redacted"]["total"] == report["total"]
    assert "integrity" not in share.meta


def test_task_and_final_output_are_scrubbed():
    t = _trace()
    t.task = f"fix {SECRET}"
    t.final_output = f"done with {AWS}"
    share, report = redact_trace(t)
    assert SECRET not in share.task
    assert AWS not in share.final_output
    assert report["total"] >= 3


def test_replacement_override():
    t = _trace()
    share, _ = redact_trace(t, replacement="[REDACTED]")
    assert "[REDACTED]" in share.steps[0].result
    assert "aws_key" not in share.steps[0].result


def test_compile_patterns_refusals():
    with pytest.raises(ValueError, match="unknown pattern"):
        compile_patterns(only=["bogus"])
    with pytest.raises(ValueError, match="empty regex"):
        compile_patterns(extra=[""])
    with pytest.raises(ValueError, match="pattern 'bad'"):
        compile_patterns(extra=["bad=[unclosed"])
    table = compile_patterns(only=["aws_key", "bearer"])
    assert set(table) == {"aws_key", "bearer"}
    table = compile_patterns(extra=["digits=[0-9]{4,}"])
    assert "digits" in table and "aws_key" in table
    table = compile_patterns(extra=["[0-9]{4,}", "h=[a-f]{2}"])
    assert "custom-1" in table and "h" in table


def test_saved_share_verifies_and_original_stays_intact(tmp_path):
    store = TraceStore(tmp_path)
    t = _trace()
    store.save(t)
    before = (tmp_path / f"{t.id}.json").read_text(encoding="utf-8")
    args = argparse.Namespace(store=str(tmp_path), trace=t.id,
                              pattern=[], only=None,
                              replacement=None, out=None, json_=False,
                              **{"json": False})
    assert cmd_redact(args) == 0
    after = (tmp_path / f"{t.id}.json").read_text(encoding="utf-8")
    assert before == after  # the original never moved
    others = [x for x in store.list_traces() if x.id != t.id]
    assert len(others) == 1
    saved = others[0]
    assert verify(saved).verdict == "intact"  # fresh chain
    assert AWS not in json.dumps(saved.to_dict())


def test_cli_out_writes_standalone(tmp_path):
    store = TraceStore(tmp_path)
    t = _trace()
    store.save(t)
    out = tmp_path / "share.json"
    args = argparse.Namespace(store=str(tmp_path), trace=t.id,
                              pattern=[], only="aws_key,openai_key",
                              replacement=None, out=str(out),
                              **{"json": True})
    rc = cmd_redact(args)
    assert rc == 0
    share = Trace.from_json(out.read_text(encoding="utf-8"))
    assert verify(share).verdict == "intact"
    assert share.meta["redacted"]["hits"] == {"aws_key": 1,
                                              "openai_key": 1}
    assert "bearer" not in share.meta["redacted"]["hits"]


def test_cli_refusals(tmp_path, capsys):
    store = TraceStore(tmp_path)
    bad = argparse.Namespace(store=str(tmp_path), trace="nope",
                             pattern=[], only=None, replacement=None,
                             out=None, **{"json": False})
    assert cmd_redact(bad) == 2
    t = _trace()
    store.save(t)
    bogus = argparse.Namespace(store=str(tmp_path), trace=t.id,
                               pattern=[], only="nope",
                               replacement=None, out=None,
                               **{"json": False})
    assert cmd_redact(bogus) == 2
    badre = argparse.Namespace(store=str(tmp_path), trace=t.id,
                               pattern=["bad=[unclosed"], only=None,
                               replacement=None, out=None,
                               **{"json": False})
    assert cmd_redact(badre) == 2
    capsys.readouterr()


def test_json_report_payload(tmp_path, capsys):
    store = TraceStore(tmp_path)
    t = _trace()
    store.save(t)
    args = argparse.Namespace(store=str(tmp_path), trace=t.id,
                              pattern=[], only=None, replacement=None,
                              out=None, **{"json": True})
    assert cmd_redact(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["source"] == t.id
    assert payload["total"] == sum(payload["hits"].values())
    assert payload["destination"].endswith(".json")
