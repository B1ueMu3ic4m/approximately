"""v222: the interop matrix — every export format, one contract.

v2.1-v2.8 added dialects one round at a time; this pins the whole
matrix at once: for every export format, a fresh store importing
that export yields traces that load, attribute and re-export
without drama — and each format's second-generation export is
byte-stable against itself.
"""


import pytest

from approximately.attributor import attribute
from approximately.exporter import NATIVE, OPENAI_JSONL, OTEL, export_store
from approximately.importer import import_file
from approximately.recorder import Recorder
from approximately.report import render_html
from approximately.store import TraceStore

FORMATS = [OPENAI_JSONL, NATIVE, OTEL]


def _seed(directory):
    store = TraceStore(directory)
    rec = Recorder("matrix run: find the bug", save=False)
    rec.tool("shell", {"cmd": "ls"}, result="ok")
    rec.tool("search", {"q": "same"}, result="same")
    rec.tool("search", {"q": "same"}, result="same")
    rec.respond("gave up", success=False)
    store.save(rec.trace)
    ok = Recorder("matrix run: fine", save=False)
    ok.respond("done", success=True)
    store.save(ok.trace)
    return store


@pytest.mark.parametrize("fmt", FORMATS)
def test_format_roundtrip_stays_healthy(tmp_path, fmt):
    source = _seed(tmp_path / "src")
    outbox = tmp_path / "out"
    outbox.mkdir()
    exported = outbox / f"t.{fmt}.json"
    export_store(source, exported, fmt=fmt)

    back = TraceStore(tmp_path / "back")
    result = import_file(exported, back)
    assert result["imported"] == 2, (fmt, result)

    for trace in back.list_traces():
        report = attribute(trace)
        html = render_html(trace, report, store=back)
        assert html, fmt

    # second generation export is byte-stable against itself
    again = outbox / f"t2.{fmt}.json"
    export_store(back, again, fmt=fmt)
    third = outbox / f"t3.{fmt}.json"
    export_store(back, third, fmt=fmt)
    assert again.read_bytes() == third.read_bytes()


def test_native_roundtrip_is_lossless(tmp_path):
    source = _seed(tmp_path / "src")
    outbox = tmp_path / "out"
    outbox.mkdir()
    export_store(source, outbox / "t.json", fmt=NATIVE)
    back = TraceStore(tmp_path / "back")
    import_file(outbox / "t.json", back)
    original = source.list_traces()[0]
    restored = back.load(original.id)
    assert restored is not None
    assert restored.to_dict() == original.to_dict()


def test_all_formats_agree_on_the_story(tmp_path):
    # the three dialects may differ in fidelity, never in verdict:
    # same task set, same success flags, after any roundtrip
    source = _seed(tmp_path / "src")
    outbox = tmp_path / "out"
    outbox.mkdir()
    for fmt in FORMATS:
        back = TraceStore(tmp_path / f"back-{fmt}")
        export_store(source, outbox / f"t.{fmt}.json", fmt=fmt)
        import_file(outbox / f"t.{fmt}.json", back)
        stories = sorted((t.task, t.success)
                         for t in back.list_traces())
        assert stories == [("matrix run: find the bug", False),
                           ("matrix run: fine", True)], fmt
