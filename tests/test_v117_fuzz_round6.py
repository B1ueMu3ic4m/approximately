"""v117: fuzz round 6 — the MCP resources surface and its friends.

Round 6 targets v0.79-v0.86: scoreboard.group_by, the resources
list/read surface, the watch alert threshold, merge's sidecar carry,
and the payload constructors' edges. Contract unchanged: documented
errors or clean skips, never a crash.
"""

import json
import random
from difflib import SequenceMatcher

from approximately.fleet import _should_alert
from approximately.mcp_server import ServerContext, handle_request
from approximately.merge import merge_store
from approximately.recorder import Recorder
from approximately.store import TraceStore

SEED = 20260925


def _call(name, arguments):
    return handle_request({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    }, ServerContext("."))


def _request(method, params, store=None):
    return handle_request({
        "jsonrpc": "2.0", "id": 1, "method": method,
        "params": params,
    }, ServerContext(store or "."))


def _assert_tool_result(resp):
    assert "result" in resp, resp
    assert resp["result"]["isError"] in (True, False)
    if resp["result"]["isError"] is False:
        json.loads(resp["result"]["content"][0]["text"])


def _weird_trace(rng, tid):
    rec = Recorder(f"f6 {tid}", save=False)
    rec.trace.id = tid
    if rng.random() >= 0.3:
        rec.tool(rng.choice(["deploy", "", None]),
                 rng.choice([{}, None]),
                 result=rng.choice([None, "", "ok"]),
                 error=rng.choice([None, "boom"]),
                 agent=rng.choice([None, "", "a"]))
        rec.respond(rng.choice(["done", ""]),
                    success=rng.choice([True, False, None]))
    return rec.trace


def test_fuzz_scoreboard_group_by(tmp_path):
    rng = random.Random(SEED)
    store = TraceStore(str(tmp_path / "s"))
    for i in range(6):
        store.save(_weird_trace(rng, f"g-{i}"))
    for group_by in [None, "", "agent", "tool", "TOOL", "\x00", 1, None,
                     ["tool"]]:
        args = {"store": str(store.directory)}
        if group_by is not None:
            args["group_by"] = group_by
        _assert_tool_result(_call("scoreboard", args))


def test_fuzz_resources(tmp_path):
    rng = random.Random(SEED + 1)
    store = TraceStore(str(tmp_path / "s"))
    for i in range(4):
        store.save(_weird_trace(rng, f"r-{i}"))
    for uri in [
        f"approximately://{store.directory}/traces/r-0",
        f"approximately://{store.directory}/traces/nope",
        f"approximately://{store.directory}/traces/",
        f"approximately://{store.directory}/annotations.jsonl",
        "approximately://", "file:///etc/passwd", "", "\x00",
        "approximately:///tmp/elsewhere/traces/x",
    ]:
        resp = _request("resources/read", {"uri": uri},
                        store=str(store.directory))
        assert "result" in resp or resp.get("error", {}).get("code") in (
            -32602,), resp
    listing = _request("resources/list", {},
                       store=str(store.directory))
    assert "result" in listing


def test_fuzz_alert_threshold(tmp_path):
    rng = random.Random(SEED + 2)

    class FakeSummary:
        def __init__(self):
            self.worsening = rng.choice([True, False])
            self.failure_rate = rng.choice([0.0, 0.2, 0.5, 1.0, -0.1])

    summaries = [FakeSummary() for _ in range(5)]
    for threshold in [None, 0.0, 0.3, 1.0, -1.0, 2.0]:
        result = _should_alert(summaries, threshold)
        assert result in (True, False)


def test_fuzz_merge_sidecar(tmp_path):
    rng = random.Random(SEED + 3)
    source = TraceStore(str(tmp_path / "src"))
    target = TraceStore(str(tmp_path / "dst"))
    for i in range(3):
        source.save(_weird_trace(rng, f"m-{i}"))
        target.save(_weird_trace(rng, f"t-{i}"))
    lines = [
        json.dumps({"trace_id": "m-0", "note": "good"}),
        "garbage line",
        "[1]",
        "null",
    ]
    (source.directory / "annotations.jsonl").write_text(
        "\n".join(lines) + "\n", encoding="utf-8")
    for conflict in ["skip", "replace", "rename"]:
        report = merge_store(source.directory, target,
                             on_conflict=conflict)
        assert isinstance(report.annotations_carried, int)
    # target sidecar stayed readable
    assert isinstance(target.annotations(), list)


def test_prose_pruning_equivalence():
    """v0.93: the ratio() upper-bound pruning must not change any
    verdict - brute-force pairwise scan and the pruned detector
    agree on a mixed corpus (verbatim repeats, paraphrases, noise)."""

    from approximately.prose import ProseRepeatDetector

    corpus = [
        "book the cheapest flight then confirm the seat",
        "book the cheapest flight then confirm the seats",
        "searching alternative routes now, this may take a moment",
        "book the cheapest flight then confirm the seat!",
        "done for today, thank you",
        "error: the upstream service returned 503",
        "book the cheapest flight then confirm the seating",
        "trying a different provider",
    ]
    detector = ProseRepeatDetector()

    # brute force: every pair, full ratio(), same verdict rules
    def brute_scan(turns):
        shingles = [_shingles_of(t) for t in turns]
        for i in range(len(turns)):
            for j in range(i + 1, len(turns)):
                if _jaccard_pair(shingles[i], shingles[j]) < 0.35:
                    continue
                if SequenceMatcher(None, turns[i],
                                   turns[j]).ratio() >= 0.8:
                    return None if i == 0 else (i, j)
        return "none"

    def _shingles_of(text, k=3):
        normalized = " ".join(text.lower().split())
        return {normalized[i:i + k]
                for i in range(0, max(1, len(normalized) - k + 1))}

    def _jaccard_pair(a, b):
        union = a | b
        return len(a & b) / len(union) if union else 0.0

    rng = random.Random(SEED + 7)
    for trial in range(30):
        picked = rng.sample(corpus, k=rng.randint(4, 7))
        rec = Recorder("pruning equivalence", save=False)
        for text in picked:
            # _turns() reads TOOL_CALL step results, not responses
            rec.tool("speak", {}, result=text)
        expected = brute_scan(picked)
        pruned = detector.detect(rec.trace)
        assert (pruned is not None) == (expected not in ("none", None)), \
            (trial, picked, expected, pruned)
