"""v335: the flag-level docs audit — every quoted span is real.

test_v316 pins door *names*; this pins the *flags*. Every
``approximately ...`` span quoted across README, TUTORIAL and
RECIPES must parse against the registered parser: the subcommand
exists and every ``--flag`` it quotes is one that door actually
takes. A renamed or dropped option now breaks the docs test that
quotes it, not a reader's cron job.
"""

import re
from pathlib import Path

from approximately.cli import build_parser

_ROOT = Path(__file__).resolve().parents[1]

_DOCS = [("README.md",), ("docs", "TUTORIAL.md"),
         ("docs", "RECIPES.md"), ("docs", "ANNOUNCEMENT.md")]


def _door_options() -> dict:
    parser = build_parser()
    doors = {}
    for act in parser._actions:
        if isinstance(act, __import__("argparse")._SubParsersAction):
            for name, sub in act.choices.items():
                opts: set = set()
                for a in sub._actions:
                    opts.update(a.option_strings)
                doors[name] = opts
    return doors


def test_every_quoted_span_uses_real_doors_and_flags():
    doors = _door_options()
    checked = 0
    problems: list = []
    for parts in _DOCS:
        text = _ROOT.joinpath(*parts).read_text(encoding="utf-8")
        for span in re.findall(r"`approximately ([^`]+)`", text):
            span = span.split(" #")[0].strip().rstrip("\\").strip()
            if not span:
                continue
            toks = span.replace("\\\n", " ").split()
            door = toks[0]
            if door not in doors:
                problems.append(f"{parts[-1]}: no door {door!r} "
                                f"(span `{span}`)")
                continue
            checked += 1
            for tok in toks[1:]:
                if tok.startswith("--"):
                    flag = tok.split("=")[0]
                    if flag not in doors[door]:
                        problems.append(
                            f"{parts[-1]}: {door} has no {flag} "
                            f"(span `{span}`)")
    assert checked >= 60, f"docs lost their example spans: {checked}"
    assert not problems, "docs quote what does not exist: " + \
        "; ".join(problems)


def test_tutorial_teaches_the_mcp_apply_gate():
    text = _ROOT.joinpath("docs", "TUTORIAL.md").read_text(
        encoding="utf-8")
    assert "plan-only" not in text, \
        "the tutorial still teaches the old plan-only contract"
    assert "apply: true" in text and "confirm: true" in text, \
        "the tutorial never teaches the two-flag MCP delete gate"


def test_receiver_docs_name_both_probes():
    text = _ROOT.joinpath("docs", "TUTORIAL.md").read_text(
        encoding="utf-8")
    assert "/health" in text and "/stats" in text, \
        "the receiver chapter must name both GET probes"
