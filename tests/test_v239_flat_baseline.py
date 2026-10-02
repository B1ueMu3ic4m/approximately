"""v239: no blind spots on a flat baseline.

ms-rounded tool latencies make MAD == 0 common — the majority of
samples identical, MAD collapses to zero, and the old detector went
quiet exactly where an outlier is most obvious.  The scale now
falls back to the mean absolute deviation; only a truly uniform
sample (every value equal) stays an honest no-op.  Swept across all
four meters: per-trace latency, fleet latency, per-trace token
burn, fleet token burn.
"""

from approximately.anomaly import (
    detect_fleet_anomalies,
    detect_fleet_token_anomalies,
    detect_latency_anomalies,
    detect_token_anomalies,
)
from approximately.recorder import Recorder
from approximately.trace import Step, Trace


def _flat_trace(latencies, tokens=None, tool="search", ident="flat"):
    trace = Trace(task=f"{ident} run", id=ident, created_at=1.0)
    for i, ms in enumerate(latencies):
        tok = tokens[i] if tokens else 100
        trace.add(Step(kind="tool_call", tool=tool, tokens=tok,
                       latency_ms=ms))
    trace.add(Step(kind="response", result="done"))
    return trace


def test_fleet_latency_sees_flat_baseline_outlier():
    store_trace = _flat_trace([40] * 10 + [9000])
    found = detect_fleet_anomalies([store_trace])
    assert len(found) == 1
    assert found[0].latency_ms == 9000


def test_fleet_latency_uniform_still_quiet():
    trace = _flat_trace([40] * 11)
    assert detect_fleet_anomalies([trace]) == []


def test_per_trace_latency_sees_flat_baseline_outlier():
    trace = _flat_trace([100] * 6 + [100, 5000])
    found = detect_latency_anomalies(trace)
    assert [a.latency_ms for a in found] == [5000]


def test_per_trace_token_sees_flat_baseline_burn():
    tokens = [100] * 6 + [100, 40000]
    trace = _flat_trace([50] * 8, tokens=tokens, ident="burn")
    found = detect_token_anomalies(trace)
    assert [a.tokens for a in found] == [40000]


def test_fleet_token_sees_flat_baseline_burn():
    trace = _flat_trace([50] * 8, tokens=[100] * 6 + [100, 40000],
                        ident="fburn")
    found = detect_fleet_token_anomalies([trace])
    assert [a.tokens for a in found] == [40000]


def test_recorder_roundtrip_keeps_the_finding(tmp_path):
    # the same trace through save/load must still flag
    from approximately.store import TraceStore

    store = TraceStore(tmp_path / "s")
    rec = Recorder("roundtrip", store=store, save=False)
    for _ in range(10):
        rec.tool("search", {}, tokens=100, latency_ms=40)
    rec.tool("search", {}, tokens=100, latency_ms=9000)
    rec.respond("done", success=True)
    store.save(rec.trace)
    found = detect_fleet_anomalies(store.list_traces())
    assert len(found) == 1 and found[0].latency_ms == 9000
