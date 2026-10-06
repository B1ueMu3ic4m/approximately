"""v309: boundaries — ISO cross-year weeks and lazy exports.

`week_compare` buckets by ISO week, and ISO weeks cross year
boundaries (2026-12-29 is 2027-W01): the bucket key is the ISO
(year, week) tuple, so the turn of the year cannot split a week or
merge two. The PEP 562 lazy exports hold their own edges: unknown
attributes raise AttributeError, __dir__ lists __all__, first touch
caches.
"""

import copy
import datetime
import pickle

import pytest

import approximately
from approximately.fleet import week_compare


def test_iso_cross_year_weeks_bucket_together():
    rows = [{"day": "2026-12-29", "failures": 3, "est_spend": 1.0,
             "traces": 5},
            {"day": "2027-01-05", "failures": 6, "est_spend": 2.0,
             "traces": 5}]
    r = week_compare(rows, today=datetime.date(2027, 1, 6))
    # 2026-12-29 is ISO 2027-W01 - the SAME week as 2027-01-04..
    assert r["this_week"]["days"] == 1
    assert r["this_week"]["failures"] == 6
    assert r["last_week"]["failures"] == 3
    assert r["deltas"]["failures"] == 1.0


def test_lazy_export_edges():
    # unknown attributes are AttributeError, not ImportError
    with pytest.raises(AttributeError, match="has no attribute"):
        approximately.__getattribute__("nope")
    # __dir__ reports the full __all__
    assert set(approximately.__all__) <= set(dir(approximately))
    # dunder lookups never import anything
    with pytest.raises(AttributeError):
        approximately.__getattribute__("__sphinx_does_not_exist__")


def test_lazy_exports_survive_copy_and_pickle():
    # the cached class survives the usual object machinery
    assert copy.copy(approximately.Step) is approximately.Step
    assert pickle.dumps(approximately.__version__)


def test_week_compare_leap_week():
    # 2020 week 53 exists (leap-week year); the ISO key holds
    rows = [{"day": "2020-12-31", "failures": 7, "est_spend": 1.0,
             "traces": 4},
            {"day": "2021-01-04", "failures": 1, "est_spend": 1.0,
             "traces": 4}]
    r = week_compare(rows, today=datetime.date(2021, 1, 6))
    assert r["usable"] is True
    assert r["this_week"]["failures"] == 1
    assert r["last_week"]["failures"] == 7  # ISO 2020-W53
