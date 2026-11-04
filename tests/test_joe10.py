"""The Joe 10's rules, against an independent reading of PREREGISTRATION-JOE10.md, and its daily run. No network."""
import datetime as dt
import random

import pytest

from forward import joe10, rules, run
from tests.test_forward import FakeMarket


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
    market = FakeMarket(codes, dt.date(2027, 1, 15))
    monkeypatch.setattr(run.eodhd, "daily", market.daily)
    monkeypatch.setattr(run.eodhd, "largest", market.largest)
    monkeypatch.setattr(run.eodhd, "company", market.company)
    monkeypatch.setattr(joe10, "STATE", tmp_path / "joe10.json")
    monkeypatch.setattr(joe10, "TRACK", tmp_path / "joe10.csv")
    monkeypatch.setattr(joe10, "REPORTS", tmp_path / "reports")
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)

    class Today(dt.date):
        value = dt.date(2026, 11, 3)
        @classmethod
        def today(cls):
            return cls.value
    monkeypatch.setattr(run.dt, "date", Today)

    joe10.init()
    assert joe10.load()["started"] is None
    Today.value = dt.date(2027, 1, 15)
    joe10.daily()
    state = joe10.load()
    assert state["started"] == "2026-11-04"
    assert "rebalance 2026-12" in state["done"]
    assert len(state["portfolio"]["weights"]) == 10
    with joe10.TRACK.open() as f:
        assert len(f.readlines()) > 40
