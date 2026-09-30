"""v221: the CLI tour — real argv through every wired door.

Per-command tests own the semantics; this round owns the wiring:
`main()` with actual argv lists, so an argparse default that drifts
from what a handler reads (a renamed flag, a missing dest) fails
here instead of in someone's shell.  One store, one pass through
the doors a new user walks.
"""

import json

import pytest

from approximately.cli import main
from approximately.recorder import Recorder
from approximately.store import TraceStore


@pytest.fixture()
def populated_store(tmp_path):
    store = TraceStore(tmp_path / "s")
    rec = Recorder("checkout fails on discount", save=False)
    rec.tool("cart", {"sku": "X"}, result="added")
    rec.tool("search", {"q": "same"}, result="same")
    rec.tool("search", {"q": "same"}, result="same")
    rec.respond("gave up", success=False)
    store.save(rec.trace)
    rec2 = Recorder("browse works", save=False)
    rec2.respond("done", success=True)
    store.save(rec2.trace)
    return store


def _run(capsys, *argv):
    code = main(list(argv))
    return code, capsys.readouterr().out


def test_doctor_door(tmp_path, capsys):
    _seed_store(tmp_path)
    code, out = _run(capsys, "doctor", "--store", str(tmp_path / "s"))
    assert code == 0
    assert "healthy" in out


def test_stats_door(tmp_path, capsys):
    store = _seed_store(tmp_path)
    code, out = _run(capsys, "stats", "--store", str(store.directory))
    assert code == 0
    assert "traces" in out.lower()


def test_stats_price_door(tmp_path, capsys):
    store = _seed_store(tmp_path)
    code, out = _run(capsys, "stats", "--store", str(store.directory),
                     "--price-per-1k", "2.0")
    assert code == 0
    assert "est. spend" in out


def test_query_door(tmp_path, capsys):
    store = _seed_store(tmp_path)
    code, out = _run(capsys, "query", "--store", str(store.directory),
                     "success == false", "--json")
    assert code == 0
    rows = json.loads(out)
    assert len(rows) == 1


def test_anomalies_tokens_door(tmp_path, capsys):
    store = _seed_store(tmp_path)
    code, out = _run(capsys, "anomalies", "--store",
                     str(store.directory), "latest", "--tokens")
    assert code == 0
    assert "no token anomalies" in out or "token anomaly" in out


def test_export_import_roundtrip_door(tmp_path, capsys):
    store = _seed_store(tmp_path)
    outbox = tmp_path / "out"
    outbox.mkdir()
    code, _ = _run(capsys, "export", "--store", str(store.directory),
                   str(outbox / "t.jsonl"))
    assert code == 0
    code, out = _run(capsys, "import", "--store",
                     str(tmp_path / "back"), str(outbox / "t.jsonl"))
    assert code == 0
    assert "imported" in out


def test_otel_export_import_doors(tmp_path, capsys):
    store = _seed_store(tmp_path)
    outbox = tmp_path / "out"
    outbox.mkdir()
    code, _ = _run(capsys, "export", "--store", str(store.directory),
                   str(outbox / "t.otlp.json"), "--format", "otel")
    assert code == 0
    code, out = _run(capsys, "import", "--store",
                     str(tmp_path / "back"),
                     str(outbox / "t.otlp.json"))
    assert code == 0
    assert "imported" in out


def test_spool_once_door(tmp_path, capsys):
    store = _seed_store(tmp_path)
    spool = tmp_path / "spool"
    spool.mkdir()
    rec = Recorder("spooled", save=False)
    rec.respond("done", success=True)
    (spool / "a.jsonl").write_text(
        json.dumps(rec.trace.to_dict()) + "\n", encoding="utf-8")
    code, out = _run(capsys, "spool", "--store", str(store.directory),
                     str(spool), "--once")
    assert code == 0
    assert "spool pass 1" in out


def test_changelog_door(tmp_path, capsys):
    code, out = _run(capsys, "changelog", "--plan",
                     "docs/PLAN.md", "-o", str(tmp_path / "c.md"))
    assert code == 0
    assert "wrote" in out


def _seed_store(tmp_path):
    store = TraceStore(tmp_path / "s")
    rec = Recorder("checkout fails on discount", save=False)
    rec.tool("cart", {"sku": "X"}, result="added")
    rec.respond("gave up", success=False)
    rec.trace.steps[0].tokens = 2_000
    store.save(rec.trace)
    rec2 = Recorder("browse works", save=False)
    rec2.respond("done", success=True)
    rec2.trace.steps[0].tokens = 1_000
    store.save(rec2.trace)
    return store
