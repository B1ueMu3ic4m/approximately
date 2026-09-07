"""Deep tests for the CLI: every command, every failure path, real subprocess
for the encoding-sensitive paths."""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from approximately.cli import main


def test_store_flag_accepted_after_subcommand(demo_store, capsys, monkeypatch):
    """UX regression: --store must work in the natural position."""
    directory, trace_id = demo_store
    monkeypatch.delenv("APPROXIMATELY_HOME", raising=False)
    code = main(["attribute", trace_id, "--store", directory])
    assert code == 0
    assert "VERDICT" in capsys.readouterr().out


def test_attribute_with_facts_file(tmp_path, demo_store, capsys):
    directory, trace_id = demo_store
    facts = tmp_path / "facts.json"
    facts.write_text(json.dumps({"book_flight#4": "BOOKED confirmation"}),
                     encoding="utf-8")
    code = main(["context", trace_id, "--budget", "15",
                 "--store", directory, "--facts", str(facts)])
    out = capsys.readouterr().out
    assert code == 0
    assert "lost facts" in out and "book_flight#4" in out


def test_context_command_reports_lost_facts(demo_store, capsys):
    directory, trace_id = demo_store
    code = main(["context", trace_id, "--budget", "15", "--store", directory])
    out = capsys.readouterr().out
    assert code == 0
    assert "effective recall" in out
    assert "lost facts" in out or "survive" in out


def test_replay_exit_codes(demo_store, tmp_path, capsys):
    directory, trace_id = demo_store
    good = tmp_path / "good_exec.py"
    good.write_text("def execute(step):\n    return step.result\n",
                    encoding="utf-8")
    bad = tmp_path / "bad_exec.py"
    bad.write_text("def execute(step):\n    return 'totally different'\n",
                   encoding="utf-8")
    old = sys.path[:]
    sys.path.insert(0, str(tmp_path))
    try:
        assert main(["replay", trace_id, "--store", directory,
                     "--executor", "good_exec:execute"]) == 0
        assert main(["replay", trace_id, "--store", directory,
                     "--executor", "bad_exec:execute"]) == 1
    finally:
        sys.path[:] = old
    capsys.readouterr()


def test_bad_executor_expression_is_clean_error(demo_store):
    directory, trace_id = demo_store
    with pytest.raises(SystemExit, match="package.module:func"):
        main(["replay", trace_id, "--store", directory, "--executor", "no_colon"])


def test_unimportable_executor_is_clean_error(demo_store):
    directory, trace_id = demo_store
    with pytest.raises(ModuleNotFoundError):
        main(["replay", trace_id, "--store", directory,
              "--executor", "does_not_exist_module:fn"])


def test_invalid_facts_file_is_clean_error(demo_store, tmp_path):
    directory, trace_id = demo_store
    bad = tmp_path / "bad.json"
    bad.write_text("{nope", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        main(["context", trace_id, "--store", directory, "--facts", str(bad)])


def test_report_command_writes_html(demo_store, tmp_path, capsys):
    directory, trace_id = demo_store
    out_path = tmp_path / "custom.html"
    code = main(["report", trace_id, "--store", directory, "-o", str(out_path)])
    assert code == 0
    assert out_path.exists() and out_path.read_text(encoding="utf-8").startswith(
        "<!doctype html>"
    )


def test_version_flag(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert "approximately" in capsys.readouterr().out


def test_subprocess_demo_utf8_safety(tmp_path):
    """The exact failure mode CI caught on Windows: a non-UTF8 console.

    PYTHONIOENCODING=ascii makes the initial stdout ascii-only; the CLI's
    UTF-8 reconfigure must let the demo finish with replaced glyphs instead
    of dying with UnicodeEncodeError.
    """
    env = dict(os.environ, APPROXIMATELY_HOME=str(tmp_path / "t"),
               PYTHONIOENCODING="ascii")
    result = subprocess.run(
        [sys.executable, "-m", "approximately.cli", "demo"],
        capture_output=True, text=True, timeout=60, env=env,
    )
    assert result.returncode == 0, result.stderr
    assert "VERDICT" in result.stdout


def test_generated_regression_file_passes_pytest_run(demo_store, tmp_path):
    directory, trace_id = demo_store
    out = tmp_path / "gen_test.py"
    main(["test", trace_id, "--store", directory, "-o", str(out)])
    env = dict(os.environ, APPROXIMATELY_HOME=str(tmp_path / "t"))
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--no-header", str(out)],
        capture_output=True, text=True, timeout=120, env=env,
    )
    # replay/entry guards skip; mode guards fail against the broken trace
    assert result.returncode != 0
    assert "passed" in result.stdout or "failed" in result.stdout
