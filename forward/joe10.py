"""The Joe 10: the 10 largest US companies, Constant Weight, held at 15% volatility (PREREGISTRATION-JOE10.md).

    python -m forward.joe10 init      # freeze the starting holdings; the track starts at the next close
    python -m forward.joe10 daily     # bring the track up to the latest close (does nothing before init)

State in state/joe10.json; the series in data/joe10.csv; monthly reports in reports/joe10-YYYY-MM.md.
The portfolio's rules are the pure functions `Portfolio.close` and `Portfolio.rebalance`; the backtest uses the same code.
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

from . import common, eodhd, rules

# The Joe 10's rules (frozen).
SIZE = 10
TARGET = 0.15            # volatility target: about SPY's average month (2009-2026)
SHARE_BAND = 0.02        # the thermostat trades only when its target differs from the stock share by more than 2 points
WEIGHT_BAND = 0.005      # otherwise a holding is traded back when it is more than 0.5% of the portfolio off its target
SALE_FEE = 0.000021      # the SEC fee, 0.21 bp on sales
EXCLUDED: set[str] = set()

ROOT = common.ROOT
STATE = ROOT / "state" / "joe10.json"
TRACK = ROOT / "data" / "joe10.csv"
REPORTS = ROOT / "reports"
FIELDS = ["date", "stock_share", "joe10", "spy"]

# The starting holdings: the September 2026 quarter, ranked at the close of September 11, 2026 and rebalanced at the close of
# September 18, 2026; shares outstanding as reported for June 30, 2026 (Berkshire in Class B equivalents; Alphabet held
# through GOOGL, valued at its whole company).
SEPTEMBER = {
    "ranked": "2026-09-11",
    "rebalanced": "2026-09-18",
    "shares": {
        "NVDA": 24_391_000_000, "AAPL": 14_714_676_000, "GOOGL": 12_309_000_000, "MSFT": 7_453_000_000,
        "AMZN": 10_903_000_000, "AVGO": 4_876_000_000, "META": 2_566_000_000, "TSLA": 3_540_000_000,
        "MU": 1_145_000_000, "BRK-B": 2_154_000_000,
    },
}


@dataclass
class Portfolio:
    """Holdings in units of each listing's adjusted (total-return) price, plus cash earning nothing."""
    weights: dict[str, float]                       # Constant Weight targets, set at each rebalance
    units: dict[str, float] = field(default_factory=dict)
    cash: float = 1.0
    sleeve_returns: list[float] = field(default_factory=list)
    stocks_after: float | None = None               # the stock holdings' value after the last close's trades

    def value(self, adjusted: dict[str, float]) -> float:
        return self.cash + sum(u * adjusted[c] for c, u in self.units.items())

    def _trade_to(self, targets: dict[str, float], adjusted: dict[str, float]) -> None:
        for code in sorted(set(self.units) | set(targets)):
            have = self.units.get(code, 0.0) * adjusted[code]
            want = targets.get(code, 0.0)
            if want < have:
                self.cash += (have - want) * (1 - SALE_FEE)
            else:
                self.cash -= want - have
            if want > 0:
                self.units[code] = want / adjusted[code]
            else:
                self.units.pop(code, None)

    def start(self, adjusted: dict[str, float]) -> None:
        """Invest at the thermostat's first reading (the sleeve's returns so far set it)."""
        share = min(1.0, TARGET / rules.volatility(self.sleeve_returns[-rules.WINDOW:]))
        value = self.value(adjusted)
        self._trade_to({c: value * share * w for c, w in self.weights.items()}, adjusted)
        self.stocks_after = sum(u * adjusted[c] for c, u in self.units.items())

    def close(self, adjusted: dict[str, float]) -> float:
        """One close: returns the stock sleeve's return. Then the thermostat and the weights are checked, and traded."""
        stocks = sum(u * adjusted[c] for c, u in self.units.items())
        sleeve = stocks / self.stocks_after - 1 if self.stocks_after else 0.0
        self.sleeve_returns = (self.sleeve_returns + [sleeve])[-(rules.WINDOW + 5):]
        value = self.cash + stocks
        current = stocks / value
        target = min(1.0, TARGET / rules.volatility(self.sleeve_returns[-rules.WINDOW:]))
        if abs(target - current) > SHARE_BAND:
            self._trade_to({c: value * target * w for c, w in self.weights.items()}, adjusted)     # every holding
        else:
            targets = {c: value * current * w for c, w in self.weights.items()}
            off = {c: t for c, t in targets.items() if abs(self.units.get(c, 0.0) * adjusted[c] - t) > WEIGHT_BAND * value}
            if off:
                keep = {c: self.units[c] * adjusted[c] for c in self.units if c not in off}
                self._trade_to({**keep, **off}, adjusted)
        self.stocks_after = sum(u * adjusted[c] for c, u in self.units.items())
        return sleeve

    def rebalance(self, values: dict[str, float], adjusted: dict[str, float]) -> None:
        """New members and weights (market value at the rebalance close); every holding traded to its target."""
        total = sum(values.values())
        self.weights = {c: v / total for c, v in values.items()}
        value = self.value(adjusted)
        share = (value - self.cash) / value if value else 0.0
        self._trade_to({c: value * share * w for c, w in self.weights.items()}, adjusted)
        self.stocks_after = sum(u * adjusted[c] for c, u in self.units.items())


def weights_from(shares: dict[str, float], closes: dict[str, float]) -> dict[str, float]:
    values = {c: s * closes[c] for c, s in shares.items()}
    total = sum(values.values())
    return {c: v / total for c, v in values.items()}


def load() -> dict:
    return json.loads(STATE.read_text())


def save(state: dict) -> None:
    STATE.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")


def portfolio_of(state: dict) -> Portfolio:
    p = state["portfolio"]
    return Portfolio(p["weights"], p["units"], p["cash"], p["sleeve_returns"], p["stocks_after"])


def store(state: dict, p: Portfolio) -> None:
    state["portfolio"] = {"weights": p.weights, "units": p.units, "cash": p.cash,
                          "sleeve_returns": p.sleeve_returns, "stocks_after": p.stocks_after}


def init() -> None:
    if STATE.exists():
        sys.exit("The Joe 10 is already initialized.")
    rebalanced = dt.date.fromisoformat(SEPTEMBER["rebalanced"])
    data = common.bars(list(SEPTEMBER["shares"]), rebalanced, rebalanced)
    closes = {c: s[rebalanced]["close"] for c, s in data.items()}
    adjusted = {c: s[rebalanced]["adjusted"] for c, s in data.items()}
    p = Portfolio(weights_from(SEPTEMBER["shares"], closes))
    p._trade_to({c: w for c, w in p.weights.items()}, adjusted)      # before the start: fully invested, for the sleeve's history
    p.cash = 0.0
    p.stocks_after = 1.0
    state = {"frozen_on": dt.date.today().isoformat(), "started": None, "last_date": rebalanced.isoformat(),
             "pending": None, "done": ["rank 2026-09", "rebalance 2026-09"], "joe10": None, "spy": None, "spy_adjusted": None}
    store(state, p)
    save(state)
    advance(state)


def rank_as_of(day: dt.date) -> dict:
    pool = eodhd.largest(100)
    candidates = []
    for code in pool:
        info = eodhd.company(code, day)
        prices = eodhd.daily(code, day - dt.timedelta(days=7), day)
        if not prices:
            continue
        bar = prices[max(prices)]
        candidates.append(rules.Candidate(code, info["cik"], info["name"], info["type"], info["country"], info["exchange"],
                                          bar["close"], bar["volume"], rules.in_class_units(code, info["shares"])))
    top = rules.rank(candidates, SIZE, EXCLUDED, set())
    chosen = {code for code, _ in top}
    return {"ranked": day.isoformat(), "shares": {c.code: c.shares for c in candidates if c.code in chosen}}


def advance(state: dict) -> None:
    p = portfolio_of(state)
    last = dt.date.fromisoformat(state["last_date"])
    today = dt.date.today()
    data = common.bars(sorted(set(p.weights) | set(p.units) | {"SPY"}), last - dt.timedelta(days=10), today)
    rows = []
    for day in sorted(d for d in data["SPY"] if d > last):
        previous = dt.date.fromisoformat(state["last_date"])
        for kind, target, quarter in common.quarter_events(previous, day):
            key = f"{kind} {quarter}"
            if key in state["done"]:
                continue
            if kind == "rank":
                state["pending"] = rank_as_of(previous)
            elif state["pending"]:
                new = set(state["pending"]["shares"]) - set(data)
                if new:
                    data.update(common.bars(new, previous - dt.timedelta(days=10), today))
                closes = {c: data[c][max(d for d in data[c] if d <= previous)]["close"] for c in state["pending"]["shares"]}
                p.rebalance({c: s * closes[c] for c, s in state["pending"]["shares"].items()}, common.adjusted_on(data, previous))
                state["pending"] = None
            state["done"].append(key)

        adjusted = common.adjusted_on(data, day)
        spy = data["SPY"][day]["adjusted"]
        frozen = dt.date.fromisoformat(state["frozen_on"])
        if state["started"] is None:
            # Before the start the sleeve is held fully invested at its weights, to give the thermostat its history.
            stocks = sum(u * adjusted[c] for c, u in p.units.items())
            p.sleeve_returns = (p.sleeve_returns + [stocks / p.stocks_after - 1])[-(rules.WINDOW + 5):]
            p._trade_to({c: stocks * w for c, w in p.weights.items()}, adjusted)
            p.cash, p.stocks_after = 0.0, stocks
            if day > frozen and len(p.sleeve_returns) >= rules.WINDOW:
                scale = 1.0 / stocks                                   # the track starts at 1.0
                p.units = {c: u * scale for c, u in p.units.items()}
                p.stocks_after = 1.0
                p.start(adjusted)
                state["started"], state["joe10"], state["spy"], state["spy_adjusted"] = day.isoformat(), p.value(adjusted), 1.0, spy
        else:
            p.close(adjusted)
            state["joe10"] = p.value(adjusted)
            state["spy"] *= spy / state["spy_adjusted"]
            state["spy_adjusted"] = spy
        state["last_date"] = day.isoformat()
        if state["started"] is not None:
            share = (state["joe10"] - p.cash) / state["joe10"]
            rows.append({"date": day.isoformat(), "stock_share": f"{share:.6f}", "joe10": f"{state['joe10']:.8f}",
                         "spy": f"{state['spy']:.8f}"})
    store(state, p)
    save(state)
    if rows:
        new = not TRACK.exists()
        with TRACK.open("a", newline="") as f:
            w = csv.DictWriter(f, FIELDS)
            if new:
                w.writeheader()
            w.writerows(rows)


def report(month: str) -> Path | None:
    with TRACK.open() as f:
        rows = [r for r in csv.DictReader(f) if r["date"][:7] <= month]
    if len(rows) < 3:
        return None
    dates = [dt.date.fromisoformat(r["date"]) for r in rows]
    joe = [float(r["joe10"]) for r in rows]
    spy = [float(r["spy"]) for r in rows]
    j, s = common.stats(joe, dates), common.stats(spy, dates)
    scale = j["volatility"] / s["volatility"] if j["volatility"] and s["volatility"] else 1.0
    mixed = [1.0]
    for a, b in zip(spy, spy[1:]):
        mixed.append(mixed[-1] * (1 + scale * (b / a - 1)))
    m = common.stats(mixed, dates)
    pct = lambda x: "n/a" if x is None else f"{x:.1%}"
    line = lambda name, x, v: f"| {name} | {pct(x['total'])} | {pct(x['annual'])} | {pct(x['volatility'])} | {pct(x['worst'])} | ${500_000 * v:,.0f} |"
    text = "\n".join([
        f"# The Joe 10 forward test: {month}", "",
        f"From the close of {rows[0]['date']} to the close of {rows[-1]['date']}. Hypothetical performance of frozen, published rules"
        " (PREREGISTRATION-JOE10.md), computed from closing prices; not an account, not a recommendation. As in an IRA: no tax;"
        " the SEC fee is the only trading cost; cash earns nothing.", "",
        "| | Total return | Annual return | Volatility | Worst drop | $500,000 is now |", "|---|---|---|---|---|---|",
        line("Joe 10", j, joe[-1]), line("SPY", s, spy[-1]), line(f"SPY + {1 - scale:.0%} cash (same risk)", m, mixed[-1]), "",
        f"Stock share today: {float(rows[-1]['stock_share']):.0%}. Annual return is shown once the track is a year old.", ""])
    REPORTS.mkdir(exist_ok=True)
    path = REPORTS / f"joe10-{month}.md"
    path.write_text(text)
    return path


def daily() -> None:
    if not STATE.exists():
        return
    state = load()
    before = state["last_date"]
    advance(state)
    if state["started"] and before[:7] != state["last_date"][:7]:
        path = report(before[:7])
        out = os.environ.get("GITHUB_OUTPUT")
        if path and out:
            with open(out, "a") as f:
                f.write(f"report={os.path.relpath(path, ROOT)}\nmonth={before[:7]}\n")


if __name__ == "__main__":
    {"init": init, "daily": daily}[sys.argv[1]]()
