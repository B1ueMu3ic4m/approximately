"""Edge-case coverage for trace, recorder, and store."""

from __future__ import annotations

import json

from approximately.recorder import Recorder, current_recorder
from approximately.trace import TOOL_CALL, Step

# ---- trace -----------------------------------------------------------------

def test_step_from_dict_ignores_unknown_fields():
    step = Step.from_dict({"kind": "tool_call", "tool": "t", "future_field": 1})
    assert step.tool == "t" and not hasattr(step, "future_field")


def test_trace_handles_unicode_and_emoji(store):
    task = "预订东京航班 ✈️ テスト <script>alert(1)</script>"
    with Recorder(task, store=store) as rec:
        rec.tool("搜索", {"城市": "东京", "emoji": "🈶"}, result="完成 ✅ $870")
        rec.respond("已预订 ✓")
    loaded = store.load(rec.trace.id)
    assert loaded.task == task
    assert loaded.steps[0].args["城市"] == "东京"
    assert loaded.steps[0].result.endswith("✅ $870")
    assert loaded.steps[1].result == "已预订 ✓"


def test_fingerprint_stable_across_key_order():
    a = Step(kind=TOOL_CALL, tool="t", args={"a": 1, "b": 2})
    b = Step(kind=TOOL_CALL, tool="t", args={"b": 2, "a": 1})
    assert a.fingerprint() == b.fingerprint()


def test_fingerprint_survives_unserializable_args():
    class Widget:
        def __str__(self):
            return "widget-1"

    step = Step(kind=TOOL_CALL, tool="make", args={"w": Widget()})
    assert "widget-1" in step.fingerprint()  # default=str fallback


def test_short_truncates_long_results():
    step = Step(kind=TOOL_CALL, tool="t", result="x" * 500)
    assert len(step.short()) < 100


# ---- recorder --------------------------------------------------------------

def test_nested_recorders_restore_correctly(store):
    with Recorder("outer", store=store) as outer:
        assert current_recorder() is outer
        with Recorder("inner", store=store) as inner:
            assert current_recorder() is inner
        assert current_recorder() is outer  # inner exit must not clobber outer
    assert current_recorder() is None


def test_recorder_without_store_does_not_save(tmp_path):
    with Recorder("no store", save=True) as rec:  # store=None, save=True
        rec.respond("done")
    assert rec.saved_path is None
    assert not (tmp_path / "traces").exists() or not list(
        (tmp_path / "traces").iterdir()
    )


def test_meta_survives_roundtrip(store):
    with Recorder("meta test", store=store) as rec:
        rec.tool("write_db", {}, result="ok", mutating=True, query="INSERT;--")
    loaded = store.load(rec.trace.id)
    assert loaded.steps[0].meta == {"mutating": True, "query": "INSERT;--"}


# ---- store -----------------------------------------------------------------

def test_store_load_missing_returns_none(store):
    assert store.load("does-not-exist") is None


def test_store_skips_corrupt_files(store, failing_trace):
    store.save(failing_trace)
    (store.directory / "corrupt.json").write_text("{not json", encoding="utf-8")
    traces = store.list_traces()
    assert [t.id for t in traces] == [failing_trace.id]  # corrupt skipped


def test_store_rejects_directory_as_trace(store):
    (store.directory / "iamadir.json").mkdir()
    assert store.load("iamadir.json") is None


def test_store_load_accepts_explicit_file_path(store, failing_trace, tmp_path):
    path = tmp_path / "elsewhere.json"
    path.write_text(failing_trace.to_json(), encoding="utf-8")
    loaded = store.load(str(path))
    assert loaded is not None and loaded.id == failing_trace.id


def test_store_list_orders_by_mtime(store):
    import os
    import time

    for i in range(3):
        with Recorder(f"task {i}", store=store) as rec:
            rec.respond("ok")
        time.sleep(0.01)
    traces = store.list_traces()
    assert [t.task for t in traces] == ["task 0", "task 1", "task 2"]
    # silence unused import warning for os on platforms where unused
    assert os is not None


def test_trace_json_roundtrip_preserves_none_success(store):
    with Recorder("never finished", store=store) as rec:
        rec.tool("search", {}, result="partial")
    loaded = store.load(rec.trace.id)
    assert loaded.success is None  # distinct from False
    assert json.loads(loaded.to_json())["success"] is None


def test_store_clean_removes_only_old_traces(store, failing_trace):
    import os
    import time

    store.save(failing_trace)
    old = store.directory / "old.json"
    old.write_text('{"task": "old", "steps": []}', encoding="utf-8")
    past = time.time() - 40 * 86400
    os.utime(old, (past, past))
    removed = store.clean(keep_days=30)
    assert removed == 1
    assert not old.exists()
    assert store.load(failing_trace.id) is not None


def test_store_blocks_path_traversal(store):
    assert store.load("../../etc/passwd") is None
    assert store.load("..\\..\\windows\\system32\\config") is None
