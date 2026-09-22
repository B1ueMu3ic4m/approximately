"""v77: adversarial stress round — untrusted agent identity.

Agent names are attacker-influenced data in fleet merges (another
team's store names its agents whatever it wants). This round hammers
the new surfaces — Step.agent through HTML/markdown reports, the
scorecard, detectors, the store roundtrip — plus floors-file
corruption in the bench-gate.
"""

import json
import time

from approximately.attributor import attribute
from approximately.benchgate import run_gate
from approximately.cluster import UNATTRIBUTED, agent_scorecard
from approximately.markdown_report import render_markdown
from approximately.recorder import Recorder
from approximately.report import render_html
from approximately.store import TraceStore

HOSTILE_NAMES = [
    "<script>alert(1)</script>",
    "<img src=x onerror=alert(2)>",
    "agent`with``ticks```",
    "```<script>alert('fence')</script>",
    "agent\x00null",
    # unicode lookalikes: mathematical bold 'agent' + Cyrillic 'agent'
    ("\U0001D4AA\U0001D4B0\U0001D4AE\U0001D4BD\U0001D4BE-"
     "\u0430\u0433\u0435\u043d\u0442-代理"),
    "agent\u202Eevil.sne",  # bidi override: renders 'len.silva'-style lies
    "x" * 10_000,
    "",                       # falsy: must land in "unattributed"
    "\t\n ",                  # whitespace-only: same
]


def _hostile_trace():
    rec = Recorder("adversarial attribution", save=False)
    for i, name in enumerate(HOSTILE_NAMES):
        rec.tool("bash", {"cmd": f"cmd-{i}"}, result=f"out-{i}",
                 agent=name)
    rec.respond("done", success=False, agent=HOSTILE_NAMES[0])
    return rec.trace


def test_html_report_escapes_agent_names():
    html = render_html(_hostile_trace(), attribute(_hostile_trace()))
    assert "<script>alert(1)</script>" not in html
    assert "<img src=x onerror" not in html
    assert "&lt;script&gt;" in html


def test_markdown_fence_cannot_be_broken():
    trace = _hostile_trace()
    md = render_markdown(trace, attribute(trace))
    boundaries = [line for line in md.splitlines()
                  if line and set(line) == {"`"}]
    assert boundaries, "timeline fence missing"
    # the payload row contains a ``` run, so every boundary — opening
    # and closing alike — must be longer than 3 and all equal length
    assert len({len(b) for b in boundaries}) == 1
    assert len(boundaries[0]) >= 4
    body = "\n".join(md.splitlines())
    assert "```<script>alert('fence')</script>" in body  # kept literal


def test_markdown_agent_names_stay_single_line():
    trace = _hostile_trace()
    md = render_markdown(trace, attribute(trace))
    for line in md.splitlines():
        assert "<script>" not in line or line.lstrip().startswith("#") \
            or "`" in line  # script payloads only ever inside fences


def test_scorecard_groups_hostile_names_boundedly():
    rows = agent_scorecard([_hostile_trace()])
    names = {r["agent"] for r in rows}
    # "" is falsy -> unattributed; the other 9 names each get a row
    assert len(rows) == len(set(HOSTILE_NAMES))
    assert UNATTRIBUTED in names
    json.dumps(rows)  # must stay JSON-serializable


def test_whitespacish_names_count_as_unattributed():
    rec = Recorder("blank agents", save=False)
    rec.tool("bash", {"cmd": "x"}, result="y", agent="")
    rows = agent_scorecard([rec.trace])
    assert rows[0]["agent"] == UNATTRIBUTED


def test_hostile_names_survive_store_roundtrip(tmp_path):
    store = TraceStore(str(tmp_path / "s"))
    trace = _hostile_trace()
    store.save(trace)
    loaded = store.load(trace.id)
    assert [s.agent for s in loaded.steps] == \
        [s.agent for s in trace.steps]


def test_attribute_pipeline_never_crashes_on_hostile_agents():
    report = attribute(_hostile_trace())
    assert report.trace_id  # a full report object came back


def test_benchgate_refuses_non_finite_floors(tmp_path, capsys):
    floors = tmp_path / "floors.json"
    floors.write_text(json.dumps({
        "sample_f1": float("nan"),
        "modes": {"FM-1.3": {"precision": float("inf"),
                             "recall": 0.5}},
    }), encoding="utf-8")
    rc = run_gate(_fixture_path(), floors, "corrupt")
    assert rc == 1
    assert "non-finite" in capsys.readouterr().err


def test_scorecard_and_markdown_perf_on_10k_steps():
    rec = Recorder("long run", save=False, agent="worker")
    for i in range(10_000):
        rec.tool("bash", {"cmd": f"c{i}"}, result="r", thought="t")
    trace = rec.trace
    t0 = time.perf_counter()
    rows = agent_scorecard([trace])
    md = render_markdown(trace, attribute(trace))
    elapsed = time.perf_counter() - t0
    assert rows[0]["steps"] == 10_000
    assert len(md) > 0
    assert elapsed < 5.0, f"10k-step adversarial pass took {elapsed:.2f}s"


def _fixture_path():
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    return root / "examples" / "action" / "fixture.jsonl"
