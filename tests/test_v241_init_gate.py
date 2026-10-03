"""v241: `approximately init` — gate the repo you already have.

`new` scaffolds a green-field project; `init` wires the CI quality
gate into the repo you already have: a GitHub Actions workflow that
fails the build when recorded runs breach a ceiling, a starter
price table the spend gate can read, and a .gitignore line so the
flight-recorder store never lands in git.  Idempotent: re-running
reports what exists and skips.  Nothing is ever overwritten
without --force, and .gitignore is only ever appended to — even
--force does not touch it.
"""

import json

from approximately.cli import main
from approximately.scaffold import init_scaffold


def test_init_writes_three_files(tmp_path):
    statuses = init_scaffold(tmp_path)
    assert set(statuses.values()) == {"written"}
    wf = tmp_path / ".github" / "workflows" / "agent-gate.yml"
    assert "approximately ci" in wf.read_text(encoding="utf-8")
    assert "--max-failure-rate 0.3" in wf.read_text(encoding="utf-8")
    audit_wf = (tmp_path / ".github" / "workflows" /
                "agent-audit.yml")
    audit_text = audit_wf.read_text(encoding="utf-8")
    assert "approximately audit" in audit_text
    assert "cron:" in audit_text
    prices = json.loads(
        (tmp_path / "prices.json").read_text(encoding="utf-8"))
    assert all(isinstance(v, (int, float)) and v >= 0
               for v in prices.values())     # the spend gate can load it
    assert ".agents-store/" in \
        (tmp_path / ".gitignore").read_text(encoding="utf-8")


def test_reinit_skips_everything_and_preserves(tmp_path):
    init_scaffold(tmp_path)
    wf = tmp_path / ".github" / "workflows" / "agent-gate.yml"
    wf.write_text("# hand-tuned ceilings live here", encoding="utf-8")
    statuses = init_scaffold(tmp_path)
    assert set(statuses.values()) == {"skipped"}
    assert "hand-tuned" in wf.read_text(encoding="utf-8")


def test_force_overwrites_workflow_but_never_gitignore(tmp_path):
    init_scaffold(tmp_path)
    gi = tmp_path / ".gitignore"
    gi.write_text(".agents-store/\n# keep me\n", encoding="utf-8")
    statuses = init_scaffold(tmp_path, force=True)
    wf_status = [v for k, v in statuses.items() if k.endswith(".yml")]
    assert wf_status == ["written", "written"]  # gate + audit
    assert gi.read_text(encoding="utf-8") == ".agents-store/\n# keep me\n"


def test_gitignore_append_preserves_existing_content(tmp_path):
    (tmp_path / ".gitignore").write_text("node_modules/\n*.pyc",
                                         encoding="utf-8")
    statuses = init_scaffold(tmp_path)
    assert statuses[str(tmp_path / ".gitignore")] == "appended"
    text = (tmp_path / ".gitignore").read_text(encoding="utf-8")
    assert text == "node_modules/\n*.pyc\n.agents-store/\n"


def test_init_cli_door(tmp_path, capsys):
    code = main(["init", "--store", str(tmp_path), str(tmp_path),
                 "--json"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["directory"] == str(tmp_path)
    assert len(payload["files"]) == 4


def test_init_human_output_names_next_steps(tmp_path, capsys):
    code = main(["init", "--store", str(tmp_path), str(tmp_path)])
    assert code == 0
    out = capsys.readouterr().out
    assert "written" in out and "prices.json" in out
    assert "--max-spend" in out
