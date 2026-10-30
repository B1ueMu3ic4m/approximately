"""v353: the catalog write is atomic.

``prices set`` rewrote ``prices.json`` in place — a crash
mid-write left a torn catalog for the money door to refuse until
a human fixed it. The write now lands whole in a tmp file and
``os.replace`` swaps it in: readers see the old table or the new
one, never half of either.
"""

import json
import tempfile
from pathlib import Path

import pytest

from approximately.prices import load_catalog, save_catalog, set_rate


def _store():
    return tempfile.mkdtemp()


def test_save_leaves_no_tmp_residue():
    store = _store()
    save_catalog(store, {"gpt-x": 0.5})
    assert (Path(store) / "prices.json").is_file()
    assert not (Path(store) / "prices.json.tmp").exists()
    assert load_catalog(store) == {"gpt-x": 0.5}


def test_a_failed_replace_keeps_the_old_table():
    store = _store()
    save_catalog(store, {"gpt-x": 0.5})
    import approximately.prices as prices

    real_replace = prices.os.replace

    def boom(*a, **k):
        raise OSError("disk went away mid-swap")

    prices.os.replace = boom
    try:
        with pytest.raises(OSError):
            save_catalog(store, {"gpt-x": 9.9})
    finally:
        prices.os.replace = real_replace
    assert load_catalog(store) == {"gpt-x": 0.5}, \
        "the old table survives the crash, the door stays open"
    (Path(store) / "prices.json.tmp").unlink()  # the tmp may remain


def test_set_rate_still_round_trips():
    store = _store()
    set_rate(store, "gpt-x", 0.5)
    set_rate(store, "claude-y", 1.5)
    assert load_catalog(store) == {"gpt-x": 0.5, "claude-y": 1.5}
    raw = json.loads((Path(store) / "prices.json").read_text())
    assert raw == {"gpt-x": 0.5, "claude-y": 1.5}
