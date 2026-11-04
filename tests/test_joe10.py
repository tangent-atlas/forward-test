"""The Joe 10's rules, against an independent reading of PREREGISTRATION-JOE10.md, and its daily run. No network."""
import datetime as dt
import random

import pytest

from forward import common, joe10, rules


def stock(code, value, cik=None, volume=1e6, name=None, country="US", kind="Common Stock", exchange="NASDAQ"):
    return rules.Candidate(code, cik or code, name or code + " Inc", kind, country, exchange, 100.0, volume, value / 100.0)


def test_eligibility():
    assert rules.eligible(stock("AAPL", 1e12))
    assert rules.eligible(stock("TSLA", 1e12))                         # the Joe 10 excludes nothing
    assert not rules.eligible(stock("TSM", 1e12, country="TW"))
    assert not rules.eligible(stock("SPY", 1e12, kind="ETF"))
    assert not rules.eligible(stock("EPD", 1e11, name="Enterprise Products Partners L.P."))
    assert not rules.eligible(stock("BP", 1e11, name="BP plc ADR"))
    assert not rules.eligible(stock("XYZ", 1e12, cik="1"), excluded_ciks={"1"})


def test_share_classes_are_one_company_held_through_the_most_traded_class():
    ranked = rules.rank([stock("GOOG", 4.1e12, cik="1652044", volume=2e7), stock("GOOGL", 4.2e12, cik="1652044", volume=3e7),
                         stock("BRK-A", 1.1e12, cik="1067983", volume=1e3), stock("BRK-B", 1.1e12, cik="1067983", volume=5e6),
                         stock("MSFT", 3e12)], size=5)
    assert ranked == [("GOOGL", 4.2e12), ("MSFT", 3e12), ("BRK-B", 1.1e12)]


def test_berkshire_is_counted_in_each_class_units():
    assert rules.in_class_units("BRK-B", 1_436_000) == 2_154_000_000
    assert rules.in_class_units("BRK-A", 2_154_000_000) == pytest.approx(1_436_000)
    assert rules.in_class_units("AAPL", 1_000) == 1_000


def test_quarter_dates():
    assert rules.quarter_dates(2026, 12) == (dt.date(2026, 12, 11), dt.date(2026, 12, 18))
    assert rules.quarter_dates(2027, 6) == (dt.date(2027, 6, 11), dt.date(2027, 6, 18))


class FakeMarket:
    """Business days with random prices from September 2026."""
    def __init__(self, codes, end, holidays=()):
        rnd = random.Random(1)
        self.days = [d for d in (dt.date(2026, 9, 1) + dt.timedelta(n) for n in range((end - dt.date(2026, 9, 1)).days + 1))
                     if d.weekday() < 5 and d not in holidays]
        self.series = {}
        for code in codes:
            p, s = 100.0, {}
            for d in self.days:
                p *= 1 + rnd.gauss(0.0005, 0.015)
                s[d] = {"close": p, "adjusted": p, "volume": 1e6}
            self.series[code] = s
        self.ranked_on = []

    def daily(self, code, start, end):
        return {d: v for d, v in self.series[code].items() if start <= d <= end}

    def largest(self, limit=100):
        return [c for c in self.series if c != "SPY"]

    def company(self, code, on):
        self.ranked_on.append(on)
        return {"name": code, "type": "Common Stock", "country": "US", "exchange": "NYSE", "cik": code, "shares": 1e9}


def reference(returns, weights, history):
    """The rules in words: each close, the thermostat's target from the last 21 sleeve returns; if it differs from the stock
    share by more than 2 points, every holding goes to target; otherwise a holding more than 0.5% of the portfolio off its
    target goes back to it. Sales pay 0.21 bp. Returns the portfolio's value after each close."""
    vol = lambda xs: rules.volatility(xs[-21:])
    hist = list(history)
    value = 1.0
    share = min(1.0, joe10.TARGET / vol(hist))
    hold = {c: value * share * w for c, w in weights.items()}
    cash = value - sum(hold.values())
    out = []
    for day in returns:
        before = sum(hold.values())
        hold = {c: h * (1 + day[c]) for c, h in hold.items()}
        stocks = sum(hold.values())
        hist.append(stocks / before - 1)
        value = cash + stocks
        current = stocks / value
        target = min(1.0, joe10.TARGET / vol(hist))
        if abs(target - current) > joe10.SHARE_BAND:
            want = {c: value * target * w for c, w in weights.items()}
        else:
            want = {c: (value * current * w if abs(hold[c] - value * current * w) > joe10.WEIGHT_BAND * value else hold[c])
                    for c, w in weights.items()}
        for c in hold:
            if want[c] < hold[c]:
                cash += (hold[c] - want[c]) * (1 - joe10.SALE_FEE)
            else:
                cash -= want[c] - hold[c]
        hold = want
        out.append(cash + sum(hold.values()))
    return out


def test_the_portfolio_follows_the_rules_as_written():
    rnd = random.Random(3)
    codes = ["A", "B", "C", "D"]
    weights = {"A": 0.4, "B": 0.3, "C": 0.2, "D": 0.1}
    history = [rnd.gauss(0, 0.012) for _ in range(25)]
    days = [{c: rnd.gauss(0.0004, 0.02 if c == "A" else 0.012) for c in codes} for _ in range(400)]
    expected = reference(days, weights, history)

    prices = {c: 100.0 for c in codes}
    p = joe10.Portfolio(dict(weights), cash=1.0, sleeve_returns=list(history))
    p.start(prices)
    actual = []
    for day in days:
        prices = {c: prices[c] * (1 + day[c]) for c in codes}
        p.close(prices)
        actual.append(p.value(prices))
    assert actual == pytest.approx(expected, rel=1e-12)


def test_a_rebalance_sets_new_weights_and_keeps_the_stock_share():
    prices = {"A": 10.0, "B": 20.0, "C": 5.0}
    p = joe10.Portfolio({"A": 0.5, "B": 0.5}, cash=1.0, sleeve_returns=[0.01, -0.01] * 15)
    p.start(prices)
    share = 1 - p.cash / p.value(prices)
    p.rebalance({"B": 1.0, "C": 3.0}, prices)
    assert set(p.units) == {"B", "C"}
    assert 1 - p.cash / p.value(prices) == pytest.approx(share, rel=1e-4)
    assert p.units["C"] * prices["C"] / (p.units["B"] * prices["B"]) == pytest.approx(3.0)


def test_the_daily_run_starts_after_freezing_and_rebalances_in_december(tmp_path, monkeypatch):
    codes = list(joe10.SEPTEMBER["shares"]) + ["LLY", "JPM", "SPY"]
    market = FakeMarket(codes, dt.date(2027, 1, 15), holidays={dt.date(2026, 12, 18)})
    monkeypatch.setattr(common.eodhd, "daily", market.daily)
    monkeypatch.setattr(common.eodhd, "largest", market.largest)
    monkeypatch.setattr(common.eodhd, "company", market.company)
    monkeypatch.setattr(joe10, "STATE", tmp_path / "joe10.json")
    monkeypatch.setattr(joe10, "TRACK", tmp_path / "joe10.csv")
    monkeypatch.setattr(joe10, "REPORTS", tmp_path / "reports")
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)

    class Today(dt.date):
        value = dt.date(2026, 11, 3)
        @classmethod
        def today(cls):
            return cls.value
    monkeypatch.setattr(common.dt, "date", Today)

    joe10.init()
    assert joe10.load()["started"] is None
    Today.value = dt.date(2027, 1, 15)
    joe10.daily()
    state = joe10.load()
    assert state["started"] == "2026-11-04"
    assert "rebalance 2026-12" in state["done"]
    assert dt.date(2026, 12, 11) in market.ranked_on                  # ranked at the second Friday's close
    assert len(state["portfolio"]["weights"]) == 10
    with joe10.TRACK.open() as f:
        assert len(f.readlines()) > 40
