"""approximately — the context runtime & flight recorder for AI agents.

Agents run on approximations: lossy context windows, summarized memory,
sampled traces. Approximately makes those approximations safe —
**approximate memory, exact accountability.**
"""

from __future__ import annotations

import pathlib
import re
from importlib import metadata as _metadata

from .attributor import FailureReport, attribute
from .context import (
    ContextForecast,
    ContextItem,
    ContextRuntime,
    ProbeResult,
    default_facts,
    forecast,
)
from .recorder import Recorder, agentstep, current_recorder
from .regress import render_regression
from .replayer import replay
from .report import render_html
from .store import TraceStore
from .taxonomy import all_modes, get_mode
from .trace import Step, Trace


def _dist_version() -> str:
    """The version, single-sourced from pyproject.toml.

    A source checkout reads the pyproject sitting next to the
    package — an installed distribution's metadata can be months
    stale (a 1.14.0 site-packages shadowing a 2.x checkout was
    caught printing exactly that).  Installed users fall back to
    the distribution metadata, which pip keeps in sync.
    """
    candidate = (pathlib.Path(__file__).resolve().parent.parent
                 .parent / "pyproject.toml")
    if candidate.is_file():
        match = re.search(r'^version = "(.+)"$',
                          candidate.read_text(encoding="utf-8"),
                          re.MULTILINE)
        if match:
            return match.group(1)
    try:
        return _metadata.version("approximately")
    except Exception:
        return "unknown"


__version__ = _dist_version()

__all__ = [
    "ContextForecast",
    "ContextItem",
    # context runtime
    "ContextRuntime",
    "FailureReport",
    "ProbeResult",
    # flight recorder
    "Recorder",
    "Step",
    "Trace",
    "TraceStore",
    "__version__",
    "agentstep",
    # taxonomy
    "all_modes",
    # postmortem
    "attribute",
    "current_recorder",
    "default_facts",
    "forecast",
    "get_mode",
    "render_html",
    "render_regression",
    "replay",
]
