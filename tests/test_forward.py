"""The rules and the daily run, on synthetic markets with known answers. No network."""
import datetime as dt
import json
import math
import random

import pytest

from forward import rules, run


def stock(code, value, cik=None, volume=1e6, name=None, country="US", kind="Common Stock", exchange="NASDAQ"):
    return rules.Candidate(code, cik or code, name or code + " Inc", kind, country, exchange, 100.0, volume, value / 100.0)


def test_eligibility_and_exclusions():
    assert rules.eligible(stock("AAPL", 1e12))
    assert not rules.eligible(stock("TSM", 1e12, country="TW"))
    assert not rules.eligible(stock("SPY", 1e12, kind="ETF"))
    assert not rules.eligible(stock("EPD", 1e11, name="Enterprise Products Partners L.P."))
    assert not rules.eligible(stock("BP", 1e11, name="BP plc ADR"))
    assert not rules.eligible(stock("TSLA", 1e12))
    assert not rules.eligible(stock("GOOGL", 1e12, cik="1652044"))
    assert not rules.eligible(stock("XYZ", 1e12, cik="1652044"))      # another listing of an excluded company


def test_share_classes_are_one_company_held_through_the_most_traded_class():
    ranked = rules.rank([stock("BRK-A", 1.1e12, cik="1067983", volume=1e3), stock("BRK-B", 1.1e12, cik="1067983", volume=5e6),
                         stock("MSFT", 3e12)], size=5)
    assert ranked == [("MSFT", 3e12), ("BRK-B", 1.1e12)]


def test_berkshire_is_counted_in_each_class_units():
    assert rules.in_class_units("BRK-B", 1_436_000) == 2_154_000_000
    assert rules.in_class_units("BRK-A", 2_154_000_000) == pytest.approx(1_436_000)
    assert rules.in_class_units("BRK-B", 2_154_000_000) == 2_154_000_000
    assert rules.in_class_units("AAPL", 1_000) == 1_000


def test_quarter_dates():
    assert rules.quarter_dates(2026, 12) == (dt.date(2026, 12, 11), dt.date(2026, 12, 18))
    assert rules.quarter_dates(2027, 6) == (dt.date(2027, 6, 11), dt.date(2027, 6, 18))


def test_thermostat_matches_the_backtest_loop():
    rnd = random.Random(7)
    r = [rnd.gauss(0.0005, 0.015) for _ in range(300)]
    # The backtest's loop (research/cycles in TangentAtlas.Backtest), written out.
    W, EV, COST, TG = rules.WINDOW, rules.RESET_EVERY, rules.SALE_FEE, rules.TARGET_VOLATILITY
    w = min(1, TG / rules.volatility(r[:W]))
    expected = []
    for n, i in enumerate(range(W, len(r))):
        x = r[i]; out = w * x; w = w * (1 + x) / (w * (1 + x) + (1 - w))
        if (n + 1) % EV == 0:
            tw = min(1, TG / rules.volatility(r[i - W + 1:i + 1])); out -= COST * abs(tw - w) * (1 + out); w = tw
        expected.append(out)
    t = rules.Thermostat(share=rules.stock_share(r[:W]))
    actual = [t.step(r[i], r[:i + 1]) for i in range(W, len(r))]
    assert actual == pytest.approx(expected, abs=1e-15)


def test_index_is_value_weighted_drifts_and_stays_continuous_at_a_rebalance():
    units = rules.units_at_rebalance({"A": 3.0, "B": 1.0}, {"A": 10.0, "B": 20.0})
    assert rules.index_value(units, {"A": 10.0, "B": 20.0}) == pytest.approx(1.0)
    assert rules.index_value(units, {"A": 11.0, "B": 20.0}) == pytest.approx(1.075)   # A was 75%
    again = rules.units_at_rebalance({"B": 1.0, "C": 1.0}, {"B": 20.0, "C": 5.0}, level=1.075)
    assert rules.index_value(again, {"B": 20.0, "C": 5.0}) == pytest.approx(1.075)


class FakeMarket:
    """Business days with random prices; a holiday on the third Friday of December 2026 (to test the step back)."""
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


def test_the_daily_run_starts_after_freezing_and_handles_a_quarter(tmp_path, monkeypatch):
    codes = list(run.SEPTEMBER["shares"]) + ["V", "XOM", "SPY"]
    market = FakeMarket(codes, dt.date(2027, 1, 15), holidays={dt.date(2026, 12, 18)})
    monkeypatch.setattr(run.eodhd, "daily", market.daily)
    monkeypatch.setattr(run.eodhd, "largest", market.largest)
    monkeypatch.setattr(run.eodhd, "company", market.company)
    monkeypatch.setattr(run, "STATE", tmp_path / "state.json")
    monkeypatch.setattr(run, "TRACK", tmp_path / "track.csv")
    monkeypatch.setattr(run, "REPORTS", tmp_path / "reports")
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)

    class Today(dt.date):
        value = dt.date(2026, 11, 3)
        @classmethod
        def today(cls):
            return cls.value
    monkeypatch.setattr(run.dt, "date", Today)

    run.init()
    state = run.load()
    assert state["started"] is None and state["last_date"] == "2026-11-03"
    assert len(state["index_returns"]) >= rules.WINDOW

    Today.value = dt.date(2027, 1, 15)
    run.daily()
    state = run.load()
    assert state["started"] == "2026-11-04"                       # the first close after freezing
    assert "rank 2026-12" in state["done"] and "rebalance 2026-12" in state["done"]
    assert dt.date(2026, 12, 11) in market.ranked_on              # ranked on the second Friday's close
    rows = run.read_track()
    assert rows[0]["date"] == "2026-11-04" and float(rows[0]["ken11"]) == 1.0
    # The index has 11 members after the rebalance (on Thursday, December 17: Friday was a holiday).
    assert len(state["units"]) == 11
