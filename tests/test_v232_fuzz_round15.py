"""v232: fuzz round 15 — annotations on the OTLP wire.

The triage-events feature hands analyst-controlled strings (author,
note, verdict) to a tracing backend.  Contract: nothing crashes,
nothing invents content, event names are sanitized to the OTLP-
friendly alphabet, hostile timestamps fall back to the root span's
clock, and the roundtrip stays idempotent.
"""

import json
import random

from approximately.exporter import OTEL, export_store
from approximately.importer import import_file
from approximately.recorder import Recorder
from approximately.store import TraceStore

SEED = 20261002


def _seed(tmp_path, verdict=None, author=None, note=None):
    store = TraceStore(tmp_path / "s")
    rec = Recorder("annotated", save=False)
    rec.respond("done", success=True)
    store.save(rec.trace)
    tid = rec.trace.id
    store.annotate(tid, note or "a note", author=author,
                   verdict=verdict if verdict is not None else "")
    return store, tid


def test_hostile_verdict_is_sanitized(tmp_path):
    store, _ = _seed(tmp_path, verdict="CONFIRMED ✔ ✔\n; DROP TABLE")
    out = tmp_path / "t.json"
    export_store(store, out, fmt=OTEL)
    root = (json.loads(out.read_text(encoding="utf-8"))
            ["resourceSpans"][0]["scopeSpans"][0]["spans"][0])
    name = root["events"][0]["name"]
    assert name.startswith("annotation.")
    for ch in name:
        assert ch.isascii() and (ch.isalnum() or ch in "_-."), name


def test_missing_timestamp_falls_back_to_root_clock(tmp_path):
    # an annotation with no wall-clock: the event time falls back to
    # the root span's start, not epoch 0
    from approximately.exporter import trace_to_spans

    store, _tid = _seed(tmp_path, verdict="confirmed")
    trace = store.load(_tid)
    spans = trace_to_spans(trace, [{"verdict": "confirmed",
                                    "note": "n"}])
    nanos = int(spans[0]["events"][0]["timeUnixNano"])
    assert nanos == int(spans[0]["startTimeUnixNano"]) > 0


def test_giant_note_is_capped(tmp_path):
    store, _ = _seed(tmp_path, note="x" * 100_000)
    out = tmp_path / "t.json"
    export_store(store, out, fmt=OTEL)
    raw = out.read_text(encoding="utf-8")
    root = (json.loads(raw)
            ["resourceSpans"][0]["scopeSpans"][0]["spans"][0])
    attrs = {a["key"]: a["value"] for a in
             root["events"][0]["attributes"]}
    assert len(attrs["annotation.note"]["stringValue"]) <= 8192


def test_random_annotations_roundtrip_idempotent(tmp_path):
    rng = random.Random(SEED)
    junk = ["", "\x00", "x" * 20_000, "📝", "\u202Ertl", "OK",
            "drop table; --", "a.b-c_d", None, 0, True]
    store = TraceStore(tmp_path / "s")
    rec = Recorder("fuzzed", save=False)
    rec.respond("done", success=True)
    store.save(rec.trace)
    for _ in range(12):
        store.annotate(rec.trace.id,
                       note=str(rng.choice(junk) or ""),
                       author=str(rng.choice(junk) or ""),
                       verdict=str(rng.choice(junk) or ""))
    out = tmp_path / "t.json"
    export_store(store, out, fmt=OTEL)
    back = TraceStore(tmp_path / "back")
    result = import_file(out, back)
    assert result["imported"] == 1
    second = tmp_path / "t2.json"
    export_store(back, second, fmt=OTEL)
    third = tmp_path / "t3.json"
    export_store(back, third, fmt=OTEL)
    assert second.read_bytes() == third.read_bytes()
