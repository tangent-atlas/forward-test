"""The forward test's rules, as pure functions: no network, no files. Every number the track publishes comes from these.

The rules are frozen in PREREGISTRATION.md; a change here after version 1.0 is a new test, published as such.
"""
from __future__ import annotations

import datetime as dt
import math
import re
from dataclasses import dataclass

# The thermostat (PREREGISTRATION.md, section 2).
TARGET_VOLATILITY = 0.1529      # the setting the website's Ken 11 uses
WINDOW = 21                     # trading days of index returns in the volatility estimate
RESET_EVERY = 10                # trading days between resets of the stock share
SALE_FEE = 0.0000105            # the SEC fee (0.21 bp on sales), charged as 0.105 bp on all value traded
SIZE = 11                       # companies in the index

# Ken's exclusions, by ticker and by company (SEC CIK), so a share class can't slip back in.
EXCLUDED_CODES = {"GOOGL", "GOOG", "TSLA", "META"}
EXCLUDED_CIKS = {"1652044", "1318605", "1326801"}   # Alphabet, Tesla, Meta Platforms

US_EXCHANGES = {"NYSE", "NASDAQ", "NYSE ARCA", "NYSE MKT", "AMEX", "BATS", "CBOE", "US"}
_PARTNERSHIP = re.compile(r"(\bL\.?\s?P\.?|\bLimited Partnership)\s*$", re.IGNORECASE)
_DEPOSITARY = re.compile(r"\b(ADR|ADS|American Depositary)\b", re.IGNORECASE)


@dataclass(frozen=True)
class Candidate:
    """One listing on the ranking date."""
    code: str
    cik: str
    name: str
    security_type: str
    country: str
    exchange: str
    close: float
    volume: float
    shares: float          # shares outstanding as last reported, in the units of this listing's price

    @property
    def value(self) -> float:
        return self.close * self.shares

    @property
    def dollar_volume(self) -> float:
        return self.close * self.volume


def in_class_units(code: str, shares: float) -> float:
    """EODHD reports Berkshire Hathaway's shares in Class A equivalents in most quarters and Class B equivalents in others,
    against both classes; one Class A share is 1,500 Class B shares. Every other listing is taken as reported."""
    if code == "BRK-B" and shares < 100_000_000:
        return shares * 1500
    if code == "BRK-A" and shares >= 100_000_000:
        return shares / 1500
    return shares


def eligible(c: Candidate) -> bool:
    """US common stock on a US exchange; no partnerships or depositary receipts; not one of Ken's exclusions."""
    if c.close <= 0 or c.shares <= 0:
        return False
    if c.security_type.lower() != "common stock":
        return False
    if c.exchange and c.exchange.upper() not in US_EXCHANGES:
        return False
    if c.country and c.country.upper() != "US":
        return False
    if _PARTNERSHIP.search(c.name or "") or _DEPOSITARY.search(c.name or ""):
        return False
    return c.code not in EXCLUDED_CODES and c.cik not in EXCLUDED_CIKS


def rank(candidates: list[Candidate], size: int = SIZE) -> list[tuple[str, float]]:
    """The largest companies by full market value: share classes are one company (by CIK), valued at the largest
    shares x price among its classes and held through its most traded class. Returns (code, value), largest first."""
    companies: dict[str, list[Candidate]] = {}
    for c in candidates:
        if eligible(c):
            companies.setdefault(c.cik or c.code, []).append(c)
    rows = []
    for key, classes in companies.items():
        held = max(classes, key=lambda c: (c.dollar_volume, c.code))
        rows.append((held.code, max(c.value for c in classes), key))
    rows.sort(key=lambda r: (-r[1], r[2]))
    return [(code, value) for code, value, _ in rows[:size]]


def quarter_dates(year: int, month: int) -> tuple[dt.date, dt.date]:
    """The second Friday of the month (ranking) and the third (rebalance, at its close)."""
    first = dt.date(year, month, 1)
    first_friday = first + dt.timedelta(days=(4 - first.weekday()) % 7)
    return first_friday + dt.timedelta(days=7), first_friday + dt.timedelta(days=14)


def volatility(returns: list[float]) -> float:
    """Annualized standard deviation (sample, 252 trading days a year)."""
    n = len(returns)
    mean = sum(returns) / n
    return math.sqrt(sum((r - mean) ** 2 for r in returns) / (n - 1)) * math.sqrt(252)


def stock_share(index_returns: list[float]) -> float:
    """The thermostat's setting from the last WINDOW index returns: min(1, target / volatility)."""
    return min(1.0, TARGET_VOLATILITY / volatility(index_returns[-WINDOW:]))


@dataclass
class Thermostat:
    """The portfolio's share in stocks (the rest is cash, earning nothing) and its trading-day count."""
    share: float
    day: int = 0

    def step(self, index_return: float, history: list[float]) -> float:
        """One trading day: returns the portfolio's return. `history` holds the index returns up to and including today."""
        portfolio = self.share * index_return
        self.share = self.share * (1 + index_return) / (self.share * (1 + index_return) + (1 - self.share))   # drift
        self.day += 1
        if self.day % RESET_EVERY == 0:
            target = stock_share(history)
            portfolio -= SALE_FEE * abs(target - self.share) * (1 + portfolio)
            self.share = target
        return portfolio


def units_at_rebalance(values: dict[str, float], adjusted: dict[str, float], level: float = 1.0) -> dict[str, float]:
    """Holdings in units of each listing's adjusted (total-return) price, weighted by full market value, worth `level`
    (the index's value at the rebalance, so the index is continuous): its value is then the sum of units x adjusted
    price, and its weights drift with prices until the next rebalance."""
    total = sum(values.values())
    return {code: level * value / total / adjusted[code] for code, value in values.items()}


def index_value(units: dict[str, float], adjusted: dict[str, float]) -> float:
    return sum(u * adjusted[code] for code, u in units.items())
