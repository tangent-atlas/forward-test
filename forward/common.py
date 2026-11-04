"""Helpers shared by the forward test's run: the data calendar, prices, quarter events and statistics."""
from __future__ import annotations

import datetime as dt
from pathlib import Path

from . import eodhd, rules

ROOT = Path(__file__).resolve().parent.parent


def bars(codes, start: dt.date, end: dt.date) -> dict[str, dict[dt.date, dict]]:
    return {code: eodhd.daily(code, start, end) for code in codes}


def adjusted_on(data: dict[str, dict[dt.date, dict]], day: dt.date) -> dict[str, float]:
    """Each listing's adjusted close on `day`, or its last before it (a listing that didn't trade keeps its price)."""
    out = {}
    for code, series in data.items():
        known = [d for d in series if d <= day]
        if not known:
            raise RuntimeError(f"No price for {code} on or before {day}.")
        out[code] = series[max(known)]["adjusted"]
    return out


def quarter_events(after: dt.date, until: dt.date):
    """Ranking and rebalance dates (second and third Fridays of March, June, September, December) in [after, until)."""
    for year in range(after.year, until.year + 1):
        for month in (3, 6, 9, 12):
            ranked, rebalanced = rules.quarter_dates(year, month)
            for kind, day in (("rank", ranked), ("rebalance", rebalanced)):
                if after <= day < until:
                    yield kind, day, f"{year}-{month:02d}"


def stats(values: list[float], dates: list[dt.date]) -> dict:
    returns = [b / a - 1 for a, b in zip(values, values[1:])]
    years = (dates[-1] - dates[0]).days / 365.25
    peak, worst = values[0], 0.0
    for v in values:
        peak = max(peak, v)
        worst = min(worst, v / peak - 1)
    total = values[-1] / values[0] - 1
    return {"total": total, "annual": (1 + total) ** (1 / years) - 1 if years >= 1 else None,
            "volatility": rules.volatility(returns) if len(returns) > 2 else None, "worst": worst}
