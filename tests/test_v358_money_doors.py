"""v358: the money door's boundaries, pinned.

Spend math is only as honest as the catalog: a negative rate
would make burning money look like saving it, a NaN would poison
every forecast downstream. The validator refuses them — this pins
the boundaries: finite non-negative numbers only, zero is a real
price (free models exist), and types that are not numbers are
refused outright.
"""

import math
import tempfile

import pytest

from approximately.prices import load_catalog, set_rate


def _store():
    return tempfile.mkdtemp()


def test_negative_rates_are_refused():
    store = _store()
    with pytest.raises(ValueError, match="finite and non-negative"):
        set_rate(store, "m", -1.0)
    with pytest.raises(ValueError):
        set_rate(store, "m", -1e-9)
    assert load_catalog(store) is None


def test_non_finite_rates_are_refused():
    store = _store()
    for probe in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValueError):
            set_rate(store, "m", probe)
    assert load_catalog(store) is None


def test_zero_is_a_real_price():
    store = _store()
    set_rate(store, "free-model", 0.0)
    assert load_catalog(store) == {"free-model": 0.0}


def test_non_numbers_are_refused_up_front():
    store = _store()
    with pytest.raises((ValueError, TypeError)):
        set_rate(store, "m", "cheap")
    assert load_catalog(store) is None
