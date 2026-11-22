"""v5949: the fleet dashboard reads the triage chains, and the
agent filter keeps its temper.

The survey counts notes and confirmed verdicts per box but never
said whether the triage LOG itself is intact — a broken chain on
one box is broken evidence fleet-wide. Each store section now
carries its annotation-chain verdict (JSON ``annotation_broken``;
the prose screams ``TRIAGE CHAIN BROKEN xN`` only when it is
broken, not the healthy case). And ``recall --agent`` meets
hostile input: unicode names, mixed case, an empty ``--agent ""``
(every conversation matches — the filter is off), and a fleet
where the agent only exists on the second box.
"""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _run(*args):
    return subprocess.run(
        [sys.executable, "-m", "approximately", *args],
        capture_output=True, text=True, cwd=str(ROOT),
        encoding="utf-8")


def _seed(tmp_path):
    from approximately.recorder import Recorder
    from approximately.store import TraceStore

    stores = []
    for name in ("a", "b"):
        store = TraceStore(tmp_path / name)
        rec = Recorder(f"survey target {name}", save=False)
        rec.tool("deploy", {}, result=None, error="boom")
        rec.respond("done", success=False)
        store.save(rec.trace)
        store.annotate(rec.trace.id, "looked", verdict="confirmed")
        stores.append(store)
    return stores


def _survey(tmp_path, as_json=True):
    args = ["--json"] if as_json else []
    stores = [str(tmp_path / "a"), str(tmp_path / "b")]
    return _run("fleet", *args, *stores)


def test_the_survey_reads_each_box_chain(tmp_path):
    _seed(tmp_path)
    r = _survey(tmp_path)
    payload = json.loads(r.stdout)
    broken = {s["name"]: s.get("annotation_broken")
              for s in payload["stores"]}
    assert broken == {"a": 0, "b": 0}, \
        "intact chains read as zero, loudly absent nowhere"
    # tamper box b's verdict
    path = tmp_path / "b" / "annotations.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    entry = json.loads(lines[0])
    entry["verdict"] = "false-positive"
    lines[0] = json.dumps(entry)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    r = _survey(tmp_path)
    payload = json.loads(r.stdout)
    broken = {s["name"]: s.get("annotation_broken")
              for s in payload["stores"]}
    assert broken.get("b") == 1, \
        "the dashboard names the box whose evidence broke"


def test_the_prose_screams_only_when_broken(tmp_path):
    _seed(tmp_path)
    r = _survey(tmp_path, as_json=False)
    assert "TRIAGE CHAIN BROKEN" not in r.stdout, \
        "an intact chain is quiet"
    path = tmp_path / "b" / "annotations.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    entry = json.loads(lines[0])
    entry["note"] = "quietly different"
    lines[0] = json.dumps(entry)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    r = _survey(tmp_path, as_json=False)
    assert "TRIAGE CHAIN BROKEN x1" in r.stdout, \
        "the prose screams where the operator is looking"
    section = r.stdout.split("b:")[1] if "b:" in r.stdout else ""
    assert "TRIAGE CHAIN BROKEN" in section, \
        "the scream sits in box b's line"


def test_the_agent_filter_keeps_its_temper(tmp_path):
    from approximately.recorder import Recorder
    from approximately.store import TraceStore

    store = TraceStore(tmp_path / "s")
    for task, agents in (("unicode run", ["研究元"]),
                         ("mixed case run", ["Deployer"]),
                         ("plain run", ["deployer"])):
        rec = Recorder(task, save=False)
        for name in agents:
            rec.tool("deploy", {}, result="ok", agent=name)
        rec.respond("done", success=True)
        store.save(rec.trace)
    r = _run("--store", str(store.directory), "recall",
             "--agent", "研究元", "--json")
    payload = json.loads(r.stdout)
    tasks = [e["task"] for d in payload["days"]
             for e in d["entries"]]
    assert tasks == ["unicode run"], "a CJK agent name matches"
    r = _run("--store", str(store.directory), "recall",
             "--agent", "", "--json")
    payload = json.loads(r.stdout)
    assert payload["conversations"] == 3, (
        "an empty --agent is the filter being off, not a refusal "
        "nor an empty answer")
    # a fleet where the agent only exists on the second box
    r = _run("recall", str(tmp_path / "s"), "--agent",
             "deployer", "--json")
    assert r.returncode == 0, r.stderr
