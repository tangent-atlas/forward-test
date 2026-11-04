"""The index's rules, as pure functions: no network, no files (PREREGISTRATION-JOE10.md, section 2).

A change here after the model is frozen is a new model, published as such.
"""
from __future__ import annotations

import datetime as dt
import math
import re
from dataclasses import dataclass

WINDOW = 21                     # trading days of returns in the volatility estimate

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


def eligible(c: Candidate, excluded_codes=frozenset(), excluded_ciks=frozenset()) -> bool:
    """US common stock on a US exchange; no partnerships or depositary receipts; not on an exclusion list (none by default)."""
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
    return c.code not in excluded_codes and c.cik not in excluded_ciks


def rank(candidates: list[Candidate], size: int, excluded_codes=frozenset(), excluded_ciks=frozenset()) -> list[tuple[str, float]]:
    """The largest companies by full market value: share classes are one company (by CIK), valued at the largest
    shares x price among its classes and held through its most traded class. Returns (code, value), largest first."""
    companies: dict[str, list[Candidate]] = {}
    for c in candidates:
        if eligible(c, excluded_codes, excluded_ciks):
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
