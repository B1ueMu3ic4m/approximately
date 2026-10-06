"""approximately — the context runtime & flight recorder for AI agents.

Agents run on approximations: lossy context windows, summarized memory,
sampled traces. Approximately makes those approximations safe —
**approximate memory, exact accountability.**
"""

from __future__ import annotations

import importlib
import pathlib
import re
from importlib import metadata as _metadata
from typing import Any

from .store import TraceStore
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

# PEP 562 lazy exports: `python -m approximately --version` should
# not pay for the attributor's detector tables, the HTML renderer
# and the replay engine on the way to printing a number. Every
# public name resolves on first touch and caches in globals().
_LAZY = {
    "FailureReport": "attributor",
    "attribute": "attributor",
    "ContextForecast": "context",
    "ContextItem": "context",
    "ContextRuntime": "context",
    "ProbeResult": "context",
    "default_facts": "context",
    "forecast": "context",
    "Recorder": "recorder",
    "agentstep": "recorder",
    "current_recorder": "recorder",
    "render_regression": "regress",
    "replay": "replayer",
    "render_html": "report",
    "all_modes": "taxonomy",
    "get_mode": "taxonomy",
}


def __getattr__(name: str) -> Any:

    module = _LAZY.get(name)
    if module is None:
        raise AttributeError(
            f"module {__name__!r} has no attribute {name!r}")
    value = getattr(importlib.import_module(f".{module}", __name__),
                    name)
    globals()[name] = value  # resolve once, then it is plain
    return value


def __dir__() -> list[str]:
    return sorted(__all__)


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
