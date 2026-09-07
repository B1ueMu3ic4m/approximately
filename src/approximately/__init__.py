"""approximately — the context runtime & flight recorder for AI agents.

Agents run on approximations: lossy context windows, summarized memory,
sampled traces. Approximately makes those approximations safe —
**approximate memory, exact accountability.**
"""

from __future__ import annotations

__version__ = "0.1.0"

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

__all__ = [
    # flight recorder
    "Recorder",
    "agentstep",
    "current_recorder",
    "Trace",
    "Step",
    "TraceStore",
    # postmortem
    "attribute",
    "FailureReport",
    "replay",
    "render_regression",
    "render_html",
    # context runtime
    "ContextRuntime",
    "ContextItem",
    "ContextForecast",
    "ProbeResult",
    "forecast",
    "default_facts",
    # taxonomy
    "all_modes",
    "get_mode",
    "__version__",
]
