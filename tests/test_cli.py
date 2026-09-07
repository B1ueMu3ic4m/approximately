import json

from approximately.cli import main


def test_cli_demo_end_to_end(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("APPROXIMATELY_HOME", str(tmp_path / "traces"))
    code = main(["demo"])
    out = capsys.readouterr().out
    assert code == 0
    assert "VERDICT  FM-1.3 Step Repetition" in out
    assert "SUGGESTED FIXES" in out
    assert "HTML report:" in out
    # the trace + html report live in the store
    files = list((tmp_path / "traces").iterdir())
    assert any(f.name.endswith(".json") for f in files)
    assert any(f.name.endswith(".report.html") for f in files)


def test_cli_attribute_json(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("APPROXIMATELY_HOME", str(tmp_path / "traces"))
    main(["demo"])
    capsys.readouterr()  # flush demo output
    trace_id = [f.stem for f in (tmp_path / "traces").glob("*.json")][0]
    code = main(["attribute", trace_id, "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["primary_mode"] == "FM-1.3"
    assert payload["failed"] is True
    assert len(payload["detections"]) >= 3


def test_cli_test_generates_pytest(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("APPROXIMATELY_HOME", str(tmp_path / "traces"))
    monkeypatch.chdir(tmp_path)
    main(["demo"])
    capsys.readouterr()  # flush demo output
    trace_id = [f.stem for f in (tmp_path / "traces").glob("*.json")][0]
    code = main(["test", trace_id, "-o", "test_gen.py"])
    out = capsys.readouterr().out
    assert code == 0
    assert "wrote test_gen.py" in out
    assert (tmp_path / "test_gen.py").exists()


def test_cli_taxonomy(capsys):
    assert main(["taxonomy"]) == 0
    out = capsys.readouterr().out
    assert "FM-1.3" in out and "17.14%" in out
    assert "Task Verification" in out


def test_cli_attribute_missing_trace_exits(tmp_path, monkeypatch):
    monkeypatch.setenv("APPROXIMATELY_HOME", str(tmp_path / "empty"))
    try:
        main(["attribute", "nope"])
    except SystemExit as exc:
        assert "no trace found" in str(exc)
    else:
        raise AssertionError("expected SystemExit")
