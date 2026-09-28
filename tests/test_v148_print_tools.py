"""v148: the tool inventory becomes a publishable artifact.

`approximately mcp --print-tools [PATH]` writes the exact
`tools/list` inventory as JSON — the README links the committed copy
so docs can cite the surface without counting by hand, and the file
itself is pinned against `_TOOLS` so it cannot drift.
"""

import argparse
import json

from approximately.cli import cmd_mcp
from approximately.mcp_server import _TOOLS


def test_print_tools_to_stdout(capsys):
    args = argparse.Namespace(store=".", print_tools="-")
    assert cmd_mcp(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["count"] == len(_TOOLS)
    assert [t["name"] for t in payload["tools"]] == \
        [t["name"] for t in _TOOLS]


def test_print_tools_to_file_and_drift_pin(tmp_path):
    target = tmp_path / "mcp-tools.json"
    args = argparse.Namespace(store=".", print_tools=str(target))
    assert cmd_mcp(args) == 0
    written = json.loads(target.read_text(encoding="utf-8"))
    assert written["count"] == len(_TOOLS)
    assert written["tools"] == _TOOLS


def test_committed_artifact_matches(tmp_path):
    from pathlib import Path

    artifact = Path("docs/mcp-tools.json")
    if artifact.is_file():
        written = json.loads(artifact.read_text(encoding="utf-8"))
        assert written["count"] == len(_TOOLS)
        assert written["tools"] == _TOOLS

