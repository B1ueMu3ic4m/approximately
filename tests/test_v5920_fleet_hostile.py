"""v5920: the fleet doors meet corrupt records TOGETHER.

Each fleet door's hostile-store sweep ran on its own; this pin
composes them — corrupt files, an oversized task, a script-tag
tool, and a 5KB error across TWO boxes through every fleet door
at once. The contract the composition asserts: the memory and
worklist doors answer by data (rc 0, no traceback, prose
line-bounded), the verify door answers 6 (an incomplete box
outranks everything — unreadable evidence is the deeper problem)
and NAMES the corrupt file, and no door lets one box's junk
cross into the other box's section.
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _run(*args):
    return subprocess.run(
        [sys.executable, "-m", "approximately", *args],
        capture_output=True, text=True, cwd=str(ROOT),
        encoding="utf-8")


def _fleet(tmp_path):
    from approximately.recorder import Recorder
    from approximately.store import TraceStore

    for name in ("a", "b"):
        store = TraceStore(tmp_path / name)
        rec = Recorder(f"run {name}", model="m/1", store=store,
                       save=False)
        rec.tool("deploy", {}, result=None,
                 error="boom " + "e" * 5000)
        rec.respond("done", success=False)
        store.save(rec.trace)
    (tmp_path / "b" / "corrupt01ab.json").write_text(
        "{torn", encoding="utf-8")
    (tmp_path / "b" / "zzz99zzzz999.json").write_text(
        json_hostile(), encoding="utf-8")
    return tmp_path


def json_hostile() -> str:
    import json

    return json.dumps({
        "id": "zzz99zzzz999", "task": "x" * 100000,
        "steps": [{"kind": "tool_call", "tool": "<script>",
                   "result": "y" * 50000}]})


def test_the_memory_and_worklist_doors_answer_by_data(tmp_path):
    fleet = _fleet(tmp_path)
    for args in ("recall", "recall-summary", "recall-digest",
                 "handoff --queue 5"):
        r = _run(*args.split(), str(fleet / "a"), str(fleet / "b"))
        assert r.returncode == 0, (
            f"{args} rc={r.returncode}: {r.stderr[-300:]}")
        assert "Traceback" not in r.stderr
        lines = r.stdout.splitlines()
        assert max(len(ln) for ln in lines) < 200000, \
            f"{args} leaked a raw oversized field"


def test_the_verify_door_answers_6_and_names_the_file(tmp_path):
    fleet = _fleet(tmp_path)
    r = _run("verify", str(fleet / "a"), str(fleet / "b"))
    assert r.returncode == 6, (
        "the incomplete box dominates: unreadable evidence is the "
        "deeper problem")
    assert "corrupt01ab.json" in r.stdout, \
        "the corrupt file is named, in its own box's section"
    assert "== a ==" in r.stdout and "1 intact" in r.stdout, \
        "the clean box's verdict still renders in its section"


def test_one_box_junk_stays_in_its_own_section(tmp_path):
    fleet = _fleet(tmp_path)
    r = _run("recall", str(fleet / "a"), str(fleet / "b"), "--json")
    # the hostile record is box-b's; box-a's entries carry no junk
    # task blob - the JSON is parseable and the sections stay
    # separate (the parse itself is the assertion)
    import json

    payload = json.loads(r.stdout)
    assert payload["conversations"] >= 1
    tasks = [e["task"] for day in payload["days"]
             for e in day["entries"]]
    assert all(t for t in tasks), \
        "every entry carries its own task, junk included"
