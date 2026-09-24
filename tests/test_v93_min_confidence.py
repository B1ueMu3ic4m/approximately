"""v93: attribute --min-confidence — the admission floor is tunable.

Raising the floor drops weak detections before fusion; the knob can
only raise it (max with the built-in 0.5), so a caller can never
weaken attribution by accident. Above every confidence, the report
falls back to the honest OTHER verdict.
"""

import json

from approximately.attributor import MIN_CONFIDENCE, attribute
from approximately.cli import build_parser
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _two_signal_trace():
    rec = Recorder("repair the flaky suite", save=False)
    rec.tool("bash", {"cmd": "pytest -k flaky"}, result="1 failed")
    rec.tool("bash", {"cmd": "pytest -k flaky"}, result="1 failed")
    rec.message("planner", "coder", "please apply the patch",
                requires_ack=True)
    rec.tool("write_draft", {"topic": "patch"}, result="applied")
    rec.respond("gave up", success=False)
    return rec.trace


def test_floor_default_unchanged():
    report = attribute(_two_signal_trace())
    strict = attribute(_two_signal_trace(),
                       min_confidence=MIN_CONFIDENCE)
    assert len(report.detections) == len(strict.detections)


def test_raised_floor_drops_weak_detections():
    trace = _two_signal_trace()
    base = attribute(trace)
    raised = attribute(trace, min_confidence=0.99)
    assert len(raised.detections) <= len(base.detections)
    if base.detections and all(
            d.confidence < 0.99 for d in base.detections):
        assert raised.detections == []
        assert raised.primary_mode.id == "OTHER"
        assert "confidence floor" in raised.summary


def test_floor_never_lowers():
    report = attribute(_two_signal_trace(), min_confidence=0.0)
    base = attribute(_two_signal_trace())
    assert len(report.detections) == len(base.detections)


def test_cli_flag_changes_verdict(tmp_path, capsys):
    store = TraceStore(str(tmp_path / "s"))
    trace = _two_signal_trace()
    store.save(trace)
    path = str(store.directory / trace.id)
    parser = build_parser()
    args = parser.parse_args(["attribute", path, "--json"])
    assert args.func(args) == 0
    base = json.loads(capsys.readouterr().out)

    args = parser.parse_args(["attribute", path, "--json",
                              "--min-confidence", "0.99"])
    assert args.func(args) == 0
    strict = json.loads(capsys.readouterr().out)
    assert len(strict["detections"]) < len(base["detections"])
