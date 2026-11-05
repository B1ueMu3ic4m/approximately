"""Fuzz 33: the probe meets hostile queries.

v374 gave /stats a query vocabulary (kind / contains / since);
v376 holds that parser to the fuzz contract: an ambiguous
request (a repeated parameter), a poison value (``1e309`` is
``inf``, ``nan`` matches nothing and proves everything), an
unknown word and a case-shifted word are all refusals with the
reason named — never a silent lie, never a crash. The parser is
a pure function, so the fuzz runs without a server.
"""

import pytest

from approximately.receiver import parse_stats_query


def test_the_vocabulary_parses():
    assert parse_stats_query("") == {}
    assert parse_stats_query("kind=spool") == {"kind": "spool"}
    assert parse_stats_query("contains=deploy") == \
        {"contains": "deploy"}
    assert parse_stats_query("since=123.5") == {"since": 123.5}
    assert parse_stats_query("kind=spool&since=1") == \
        {"kind": "spool", "since": 1.0}


def test_repeated_parameters_are_a_refusal():
    with pytest.raises(ValueError, match="repeated"):
        parse_stats_query("kind=a&kind=b")
    with pytest.raises(ValueError, match="repeated"):
        parse_stats_query("since=1&since=2")
    with pytest.raises(ValueError, match="repeated"):
        parse_stats_query("contains=a&contains=a&contains=a")


def test_poison_since_values_are_refused():
    with pytest.raises(ValueError, match="unix timestamp"):
        parse_stats_query("since=1e309")  # inf, not a timestamp
    with pytest.raises(ValueError, match="unix timestamp"):
        parse_stats_query("since=nan")
    with pytest.raises(ValueError, match="unix timestamp"):
        parse_stats_query("since=30m")
    with pytest.raises(ValueError, match="unix timestamp"):
        parse_stats_query("since=")


def test_unknown_and_shifted_words_are_named():
    with pytest.raises(ValueError, match="kinds"):
        parse_stats_query("kinds=spool")
    with pytest.raises(ValueError, match="KIND"):
        parse_stats_query("KIND=spool")
    with pytest.raises(ValueError, match="drop"):
        parse_stats_query("kind=spool&drop=all")


def test_empty_values_are_well_defined_not_dropped():
    # kind= with keep_blank_values: an empty kind matches rows
    # whose kind is the empty string — a shape, not a silent
    # fall-through to the global census
    assert parse_stats_query("kind=") == {"kind": ""}
    assert parse_stats_query("contains=") == {"contains": ""}


def test_weird_encodings_degrade_to_literals():
    assert parse_stats_query("contains=%zz") == \
        {"contains": "%zz"}
    assert parse_stats_query("contains=%E2%9C%93") == \
        {"contains": "✓"}
    huge = "x" * 5000
    assert parse_stats_query(f"kind={huge}") == {"kind": huge}


def test_negative_epoch_is_a_legal_timestamp():
    assert parse_stats_query("since=-5") == {"since": -5.0}
