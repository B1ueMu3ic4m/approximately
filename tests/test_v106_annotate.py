"""v106: analyst annotations — append-only sidecar, never the chain.

`annotate` attaches triage notes to a trace WITHOUT touching the
trace file: the tamper-evident hash chain must stay intact (notes
live in annotations.jsonl, an append-only audit log — a note is
never edited or removed, only superseded). Surfaces: library
(store.annotate / store.annotations), CLI `annotate` / `annotations`,
MCP tool #20 `annotate` (write with a note, read without), and both
report renderers show the notes when a store is handed in.
"""

import json

from approximately.cli import build_parser
from approximately.markdown_report import render_markdown
from approximately.mcp_server import _TOOLS, ServerContext, handle_request
from approximately.recorder import Recorder
from approximately.report import render_html
from approximately.store import TraceStore


def _store(tmp_path):
    store = TraceStore(str(tmp_path / "s"))
    rec = Recorder("annotate fixture", save=False)
    rec.trace.id = "a-1"
    rec.tool("deploy", {"env": "prod"}, result=None, error="timeout")
    rec.respond("gave up", success=False)
    store.save(rec.trace)
    return store


def _call(arguments):
    return handle_request({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "annotate", "arguments": arguments},
    }, ServerContext("."))


def _payload(resp):
    assert resp["result"]["isError"] is False, resp["result"]
    return json.loads(resp["result"]["content"][0]["text"])


def test_annotate_roundtrip_chain_intact(tmp_path):
    from approximately.integrity import verify

    store = _store(tmp_path)
    before = verify(store.load("a-1"))
    store.annotate("a-1", "deploy timed out — infra, not the agent",
                   author="oncall", verdict="confirmed")
    store.annotate("a-1", "second look: retry budget was the issue",
                   author="lead")
    rows = store.annotations("a-1")
    assert [r["verdict"] for r in rows] == ["confirmed", ""]
    assert rows[0]["author"] == "oncall"
    # the evidence chain is untouched by note-taking
    after = verify(store.load("a-1"))
    assert after.intact == before.intact
    assert after.actual_final == before.actual_final


def test_annotations_filter_and_corrupt_lines(tmp_path):
    store = _store(tmp_path)
    store.annotate("a-1", "for a-1")
    store.annotate("a-2", "for a-2")
    path = store.directory / "annotations.jsonl"
    with path.open("a", encoding="utf-8") as fh:
        fh.write('{"trace_id": "a-1", "note": "trun')   # partial write
        fh.write("\nnot json at all\n")
    # the truncated line and the garbage line are skipped, not fatal
    assert len(store.annotations("a-1")) == 1
    assert len(store.annotations()) == 2


def test_mcp_annotate_write_and_read(tmp_path):
    store = _store(tmp_path)
    payload = _payload(_call({"trace": "a-1",
                              "store": str(store.directory),
                              "note": "infra timeout",
                              "author": "oncall",
                              "verdict": "confirmed"}))
    assert payload["annotated"] is True
    assert payload["total_on_file"] == 1
    readback = _payload(_call({"trace": "a-1",
                               "store": str(store.directory)}))
    assert readback["annotations"][0]["note"] == "infra timeout"


def test_cli_annotate_and_list(tmp_path, capsys):
    store = _store(tmp_path)
    parser = build_parser()
    args = parser.parse_args(["annotate", "--store",
                              str(store.directory),
                              "a-1", "retry budget was exhausted",
                              "--author", "lead",
                              "--verdict", "confirmed"])
    assert args.func(args) == 0
    assert "1 note(s) on file" in capsys.readouterr().out

    args = parser.parse_args(["annotations", "--store",
                              str(store.directory), "--json"])
    assert args.func(args) == 0
    rows = json.loads(capsys.readouterr().out)
    assert rows[0]["verdict"] == "confirmed"


def test_reports_render_annotations(tmp_path):
    store = _store(tmp_path)
    store.annotate("a-1", "infra timeout", author="oncall",
                   verdict="confirmed")
    trace = store.load("a-1")
    from approximately.attributor import attribute

    report = attribute(trace)
    html = render_html(trace, report, store=store)
    assert "Analyst annotations" in html
    assert "infra timeout" in html
    md = render_markdown(trace, report, store=store)
    assert "### Analyst annotations" in md
    assert "infra timeout" in md
    # and stay hidden without a store
    assert "Analyst annotations" not in render_html(trace, report)


def test_annotate_registered():
    assert "annotate" in [t["name"] for t in _TOOLS]
