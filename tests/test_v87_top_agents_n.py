"""v87: the busiest-agents window is configurable.

Digest snapshots carry each store's top-3 busiest named agents by
default; `fleet --top-agents N` widens (or narrows) the window for
watch snapshots, dashboards, and fleet JSON. The honest limit stays:
`fleet --trend --agent` can only see agents inside this window — the
help text and the v81 tests keep saying so.
"""

import json

from approximately.cli import build_parser
from approximately.fleet import survey
from approximately.recorder import Recorder
from approximately.store import TraceStore


def _crew_store(tmp_path, names=("researcher", "writer", "lead",
                                 "reviewer")):
    store = TraceStore(str(tmp_path / "s"))
    for i, name in enumerate(names):
        rec = Recorder(f"run {i}", save=False)
        rec.tool("bash", {"cmd": f"c{i}"}, result="y", agent=name)
        rec.respond("done", success=False, agent=name)
        store.save(rec.trace)
    return store


def test_default_survey_keeps_three(tmp_path):
    summaries = survey([_crew_store(tmp_path).directory])
    assert len(summaries[0].top_agents) == 3


def test_survey_top_agents_n(tmp_path):
    store = _crew_store(tmp_path)
    assert len(survey([store.directory], top_agents=1)[0].top_agents) == 1
    rows = survey([store.directory], top_agents=10)[0].top_agents
    assert len(rows) == 4


def test_cli_fleet_json_honors_top_agents(tmp_path):
    store = _crew_store(tmp_path)
    parser = build_parser()
    args = parser.parse_args(["fleet", str(store.directory), "--json",
                              "--top-agents", "2"])
    import contextlib
    import io
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        args.func(args)
    payload = json.loads(buf.getvalue())
    assert len(payload["stores"][0]["top_agents"]) == 2


def test_cli_watch_writes_widened_snapshots(tmp_path):
    store = _crew_store(tmp_path)
    digests = tmp_path / "digests"
    parser = build_parser()
    args = parser.parse_args([
        "fleet", str(store.directory), "--watch", "0.01",
        "--digest-dir", str(digests), "--iterations", "1",
        "--top-agents", "4"])
    assert args.func(args) == 0
    line = (digests / sorted(p.name for p in digests.glob("digest-*.jsonl"))
            [0]).read_text().splitlines()[0]
    snap = json.loads(line)
    assert len(snap["stores"][0]["top_agents"]) == 4
