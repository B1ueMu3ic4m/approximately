"""Spend forecasting over digest history.

The trend verdicts say WHICH WAY the fleet is drifting; this module
says HOW FAST and WHAT THAT MEANS in days: a Theil-Sen slope over the
daily spend series, a horizon projection, and — given a ceiling — the
date the trend crosses it.  Linear extrapolation, honestly labeled:
robust to outliers, blind to regime changes, and wrong the moment
someone deploys something new.
"""

from __future__ import annotations

import datetime
import math
from typing import Any, Dict, List, Optional

from .report import trend_verdict


def forecast_spend(days: List[dict],
                   ceiling: Optional[float] = None,
                   horizon_days: int = 14) -> Dict[str, Any]:
    """Project the daily ``est_spend`` series forward.

    ``days`` is the trend_days shape (rows with ``day`` and
    ``est_spend``).  Returns the Theil-Sen slope, the latest value,
    the projected series for ``horizon_days``, and — with a
    ``ceiling`` — ``days_to_ceiling`` (0 when already over; ``None``
    when the trend never gets there).  Fewer than two days of
    history returns a forecast that refuses to guess.
    """
    series = [float(r.get("est_spend") or 0.0) for r in days]
    if len(series) < 2:
        return {"usable": False, "reason": "need at least two days "
                "of history", "slope": None, "latest":
                series[-1] if series else None,
                "projection": [], "days_to_ceiling": None}
    verdict, slope = trend_verdict(series)
    latest = series[-1]
    last_day = datetime.date.fromisoformat(str(days[-1]["day"]))
    projection = []
    for offset in range(1, horizon_days + 1):
        value = max(0.0, latest + slope * offset)
        projection.append({
            "day": (last_day + datetime.timedelta(days=offset))
            .isoformat(),
            "est_spend": round(value, 2),
        })
    days_to_ceiling = None
    if ceiling is not None:
        if latest > ceiling:
            days_to_ceiling = 0
        elif slope > 0:
            days_to_ceiling = math.ceil((ceiling - latest) / slope)
    return {
        "usable": True,
        "verdict": verdict,
        "slope": round(slope, 4),
        "latest": round(latest, 2),
        "ceiling": ceiling,
        "projection": projection,
        "days_to_ceiling": days_to_ceiling,
    }


def failure_budget(days: List[dict], allowance: int,
                   horizon_days: int = 14) -> Dict[str, Any]:
    """How much of the reliability allowance is spent, and when it runs out.

    ``days`` is the trend_days shape; ``allowance`` is the maximum
    number of failed runs the window may hold (the SRE error budget,
    in runs rather than nines).  Burned is the exact failed-run count
    across the window; with a rising burn the exhaustion date is the
    Theil-Sen slope projected forward — same honesty label as the
    spend forecast.  Refuses to guess on an empty window.
    """
    burned = sum(int(r.get("failures") or 0) for r in days)
    remaining = max(0, allowance - burned)
    out: Dict[str, Any] = {
        "usable": bool(days),
        "allowance": allowance,
        "burned": burned,
        "remaining": remaining,
        "burn_fraction": round(burned / allowance, 4)
        if allowance > 0 else None,
        "exhausted": burned >= allowance,
        "days_to_exhaustion": None,
        "projection": [],
    }
    if len(days) < 2:
        out["usable"] = False
        out["reason"] = "need at least two days of history"
        return out
    series = [int(r.get("failures") or 0) for r in days]
    verdict, daily_slope = trend_verdict(series)
    out["verdict"] = verdict
    out["daily_slope"] = round(daily_slope, 4)
    last_day = datetime.date.fromisoformat(str(days[-1]["day"]))
    cumulative = float(burned)
    for offset in range(1, horizon_days + 1):
        cumulative = max(0.0, cumulative + daily_slope)
        out["projection"].append({
            "day": (last_day + datetime.timedelta(days=offset))
            .isoformat(),
            "burned": round(cumulative),
            "remaining": max(0, allowance - round(cumulative)),
        })
        if (out["days_to_exhaustion"] is None
                and round(cumulative) >= allowance):
            out["days_to_exhaustion"] = offset
    if burned >= allowance:
        out["days_to_exhaustion"] = 0
    return out
