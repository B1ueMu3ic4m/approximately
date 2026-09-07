"""Shared fixtures: small synthetic traces for detector tests."""

from __future__ import annotations

import pytest

from approximately.recorder import Recorder
from approximately.store import TraceStore
from approximately.trace import Trace


@pytest.fixture
def store(tmp_path):
    return TraceStore(tmp_path / "traces")


@pytest.fixture
def clean_trace() -> Trace:
    """A healthy run: plan -> search -> verify -> respond(success)."""
    with Recorder("find the cheapest SFO to NRT flight and book it",
                  save=False) as rec:
        rec.plan("search flights, pick cheapest, book, verify")
        rec.tool("search_flights", {"from": "SFO", "to": "NRT"},
                 result="JT-044 $870")
        rec.tool("book_flight", {"flight": "JT-044", "seat": "12A"},
                 result="BOOKED #B-1", mutating=True)
        rec.tool("get_booking", {"id": "#B-1"}, result="seat 12A confirmed",
                 meta={"verify": True})
        rec.respond("Booked JT-044 seat 12A, verified.", success=True)
    return rec.trace


@pytest.fixture
def failing_trace() -> Trace:
    """Mirrors the built-in demo: repeat + no verify + premature stop."""
    with Recorder("Find the cheapest SFO-NRT flight in June and book seat 12A.",
                  save=False) as rec:
        rec.plan("Find the cheapest SFO-NRT flight and book seat 12A.")
        rec.tool("search_flights", {"origin": "SFO", "destination": "NRT"},
                 result="JT-044 $870")
        rec.tool("search_flights", {"origin": "SFO", "destination": "NRT"},
                 result="JT-044 $870", thought="double-check")
        rec.tool("search_flights", {"origin": "SFO", "destination": "NRT"},
                 result="JT-044 $870", thought="one more look")
        rec.tool("book_flight", {"flight": "JT-044", "seat": "12A"},
                 result="BOOKED #B-2231", mutating=True)
        rec.respond("Done! Booked JT-044 seat 12A.", success=False)
    return rec.trace
