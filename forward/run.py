"""The forward test, run once a trading day after the close (GitHub Actions), or by hand.

    python -m forward.run init      # freeze the starting holdings; the track starts at the next close
    python -m forward.run daily     # bring the track up to the latest close; write the month's report when a month ends

State lives in state/state.json; the published series in data/track.csv; monthly reports in reports/.
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import math
import os
import sys
from pathlib import Path

from . import eodhd, rules

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "state" / "state.json"
TRACK = ROOT / "data" / "track.csv"
REPORTS = ROOT / "reports"
FIELDS = ["date", "index_level", "stock_share", "ken11", "spy"]

# The holdings the track starts from: the September 2026 quarter, ranked at the close of September 11 and rebalanced at
# the close of September 18 (PREREGISTRATION.md, section 3). Shares outstanding as reported for June 30, 2026, in
# the units of each listing's price (Berkshire in Class B equivalents).
SEPTEMBER = {
    "ranked": "2026-09-11",
    "rebalanced": "2026-09-18",
    "shares": {
        "NVDA": 24_391_000_000, "AAPL": 14_714_676_000, "MSFT": 7_453_000_000, "AMZN": 10_903_000_000,
        "AVGO": 4_876_000_000, "MU": 1_145_000_000, "BRK-B": 2_154_000_000, "LLY": 893_700_000,
        "JPM": 2_694_200_000, "WMT": 7_999_000_000, "AMD": 1_655_000_000,
    },
}


def load() -> dict:
    return json.loads(STATE.read_text())


def save(state: dict) -> None:
    STATE.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")


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


def rank_as_of(day: dt.date) -> dict:
    """The quarter's ranking from the closes of `day`: the 11 largest eligible companies and their shares outstanding."""
    pool = eodhd.largest(100)
    candidates = []
    for code in pool:
        info = eodhd.company(code, day)
        prices = eodhd.daily(code, day - dt.timedelta(days=7), day)
        if not prices:
            continue
        bar = prices[max(prices)]
        shares = rules.in_class_units(code, info["shares"])
        candidates.append(rules.Candidate(code, info["cik"], info["name"], info["type"], info["country"],
                                          info["exchange"], bar["close"], bar["volume"], shares))
    top = rules.rank(candidates)
    chosen = {c.code: c.shares for c in candidates if c.code in {code for code, _ in top}}
    return {"ranked": day.isoformat(), "shares": chosen,
            "values": {code: round(value) for code, value in top}}


def init() -> None:
    if STATE.exists():
        sys.exit("The track is already initialized.")
    rebalanced = dt.date.fromisoformat(SEPTEMBER["rebalanced"])
    today = dt.date.today()
    data = bars(list(SEPTEMBER["shares"]), rebalanced, today)
    closes = {code: series[rebalanced]["close"] for code, series in data.items()}
    adjusted = {code: series[rebalanced]["adjusted"] for code, series in data.items()}
    values = {code: shares * closes[code] for code, shares in SEPTEMBER["shares"].items()}
    state = {
        "frozen_on": today.isoformat(),          # the track starts at the first close after this date
        "started": None,
        "last_date": rebalanced.isoformat(),
        "units": rules.units_at_rebalance(values, adjusted),
        "index_level": 1.0,
        "index_returns": [],
        "pending": None,
        "done": ["rank 2026-09", "rebalance 2026-09"],
        "thermostat": None,
        "ken11": None,
        "spy": None,
        "spy_adjusted": None,
    }
    save(state)
    advance(state)


def advance(state: dict) -> None:
    """Process every close after state['last_date'] up to the latest one EODHD has."""
    last = dt.date.fromisoformat(state["last_date"])
    today = dt.date.today()
    codes = sorted(set(state["units"]) | {"SPY"})
    data = bars(codes, last - dt.timedelta(days=10), today)
    days = sorted(d for d in data["SPY"] if d > last)          # SPY's bars are the trading calendar
    rows = []
    for day in days:
        previous = dt.date.fromisoformat(state["last_date"])
        # Quarter events dated on or after the previous close and before this one belong to the previous close.
        for kind, target, quarter in quarter_events(previous, day):
            key = f"{kind} {quarter}"
            if key in state["done"]:
                continue
            if kind == "rank":
                state["pending"] = rank_as_of(previous)
            elif state["pending"]:
                prior = adjusted_on(data, previous) if set(state["pending"]["shares"]) <= set(data) else None
                if prior is None:
                    data.update(bars(set(state["pending"]["shares"]) - set(data), previous - dt.timedelta(days=10), today))
                    prior = adjusted_on(data, previous)
                closes = {c: data[c][max(d for d in data[c] if d <= previous)]["close"] for c in state["pending"]["shares"]}
                values = {c: s * closes[c] for c, s in state["pending"]["shares"].items()}
                state["units"] = rules.units_at_rebalance(values, prior, state["index_level"])
                state["pending"] = None
            state["done"].append(key)

        level = rules.index_value(state["units"], adjusted_on(data, day))
        r = level / state["index_level"] - 1
        state["index_level"] = level
        state["index_returns"] = (state["index_returns"] + [r])[-(rules.WINDOW + 5):]
        spy = data["SPY"][day]["adjusted"]

        frozen = dt.date.fromisoformat(state["frozen_on"])
        if state["started"] is None and day > frozen and len(state["index_returns"]) >= rules.WINDOW:
            # The first close after the rules were frozen: the track starts here, at 1.0, with the thermostat set.
            state["started"] = day.isoformat()
            state["thermostat"] = {"share": rules.stock_share(state["index_returns"]), "day": 0}
            state["ken11"], state["spy"], state["spy_adjusted"] = 1.0, 1.0, spy
        elif state["started"] is not None:
            t = rules.Thermostat(**state["thermostat"])
            state["ken11"] *= 1 + t.step(r, state["index_returns"])
            state["thermostat"] = {"share": t.share, "day": t.day}
            state["spy"] *= spy / state["spy_adjusted"]
            state["spy_adjusted"] = spy

        state["last_date"] = day.isoformat()
        if state["started"] is not None:
            rows.append({"date": day.isoformat(), "index_level": f"{level:.8f}",
                         "stock_share": f"{state['thermostat']['share']:.6f}",
                         "ken11": f"{state['ken11']:.8f}", "spy": f"{state['spy']:.8f}"})
    save(state)
    if rows:
        new = not TRACK.exists()
        with TRACK.open("a", newline="") as f:
            w = csv.DictWriter(f, FIELDS)
            if new:
                w.writeheader()
            w.writerows(rows)


def read_track() -> list[dict]:
    with TRACK.open() as f:
        return list(csv.DictReader(f))


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


def report(month: str) -> Path | None:
    """The report for a finished month: since the start, Ken 11 against SPY and SPY plus cash at the same risk."""
    rows = [r for r in read_track() if r["date"][:7] <= month]
    if len(rows) < 3:
        return None
    dates = [dt.date.fromisoformat(r["date"]) for r in rows]
    ken = [float(r["ken11"]) for r in rows]
    spy = [float(r["spy"]) for r in rows]
    k, s = stats(ken, dates), stats(spy, dates)
    scale = k["volatility"] / s["volatility"] if k["volatility"] and s["volatility"] else 1.0
    mixed = [1.0]
    for a, b in zip(spy, spy[1:]):
        mixed.append(mixed[-1] * (1 + scale * (b / a - 1)))   # a fixed cash share, rebalanced daily, cash earning nothing
    m = stats(mixed, dates)
    pct = lambda x: "n/a" if x is None else f"{x:.1%}"
    line = lambda name, x, v: f"| {name} | {pct(x['total'])} | {pct(x['annual'])} | {pct(x['volatility'])} | {pct(x['worst'])} | ${500_000 * v:,.0f} |"
    text = "\n".join([
        f"# The Ken 11 forward test: {month}",
        "",
        f"From the close of {rows[0]['date']} to the close of {rows[-1]['date']}. Hypothetical performance of frozen, published rules"
        " (PREREGISTRATION.md), computed from closing prices; not an account, not a recommendation. Before taxes; the SEC fee is the only"
        " trading cost; cash earns nothing.",
        "",
        "| | Total return | Annual return | Volatility | Worst drop | $500,000 is now |",
        "|---|---|---|---|---|---|",
        line("Ken 11", k, ken[-1]),
        line(f"SPY + {1 - scale:.0%} cash (same risk)", m, mixed[-1]),
        line("SPY", s, spy[-1]),
        "",
        f"Stock share today: {float(rows[-1]['stock_share']):.0%}. Annual return is shown once the track is a year old.",
        "",
    ])
    REPORTS.mkdir(exist_ok=True)
    path = REPORTS / f"{month}.md"
    path.write_text(text)
    return path


def daily() -> None:
    state = load()
    before = state["last_date"]
    advance(state)
    # When the track has crossed into a new month, report the month that ended.
    if state["started"] and before[:7] != state["last_date"][:7]:
        path = report(before[:7])
        out = os.environ.get("GITHUB_OUTPUT")
        if path and out:
            with open(out, "a") as f:
                f.write(f"report={os.path.relpath(path, ROOT)}\nmonth={before[:7]}\n")


if __name__ == "__main__":
    {"init": init, "daily": daily}[sys.argv[1]]()
