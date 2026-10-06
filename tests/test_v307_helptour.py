"""v307: the help tour holds itself to completeness.

`approximately help` is a guided tour over the 59 doors, and the
tour is data — so the suite can hold it to the one rule that keeps
help honest: **every registered door appears exactly once**, and
every tour door is actually registered. A door added without a
tour entry fails the suite; so does a tour entry for a door that
no longer exists.
"""

import argparse

from approximately.cli import build_parser
from approximately.helptour import TOUR, render_index, render_topic, topics, tour_entries


def _registered_doors():
    parser = build_parser()
    return set(parser._subparsers._group_actions[0].choices)


def test_tour_covers_every_door_exactly_once():
    registered = _registered_doors()
    toured = tour_entries()
    assert len(toured) == len(set(toured)), "a door is toured twice"
    missing = registered - set(toured)
    ghost = set(toured) - registered
    assert not missing, f"doors with no tour entry: {sorted(missing)}"
    assert not ghost, f"tour names doors that do not exist: {sorted(ghost)}"


def test_seven_topics_with_real_doors():
    assert len(TOUR) == 7
    for name, (blurb, doors) in TOUR.items():
        assert blurb, name
        assert doors, name
        assert all(" " not in door for door, _ in doors), name


def test_render_topic_and_index():
    prose = render_topic("operate")
    assert prose.startswith("operate — ")
    assert "tail" in prose and "triage" in prose
    index = render_index()
    assert "topics" in index
    for name in topics():
        assert name in index


def test_render_topic_unknown_refuses():
    try:
        render_topic("nope")
        raise AssertionError("should refuse")
    except ValueError as exc:
        assert "topics:" in str(exc)


def test_cli_help_door(tmp_path, capsys):
    from approximately.cli import cmd_help

    assert cmd_help(argparse.Namespace(store=".", topic=None)) == 0
    assert "topics" in capsys.readouterr().out
    assert cmd_help(argparse.Namespace(store=".",
                                       topic="operate")) == 0
    assert "on-call loop" in capsys.readouterr().out
    assert cmd_help(argparse.Namespace(store=".",
                                       topic="nope")) == 2
    capsys.readouterr()
