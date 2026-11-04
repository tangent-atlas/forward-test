# Pre-registration §19: the Ken 11 forward test

*Frozen November 3, 2026, by Tangent Atlas, before the track's first close. Archived on Zenodo as version 1.0 of this repository; every later version adds results only. A change to the rules after version 1.0 is a new test, published as such, and this one keeps running unchanged.*

## 1. What is tested

The Ken 11 is the example on tangentatlas.com/your-plan: a personal index of the 11 largest US companies, after four companies its owner chooses to leave out, with its cash reset every two weeks so that its risk stays where its owner set it. Backtested from April 2009 to October 2026 it returned 15.2% a year at 14.2% volatility, against 12.9% for an S&P 500 fund (SPY) plus cash at the same volatility, with a worst drop of −18% against −29%. Backtests of new index strategies usually show far more than they earn once live (Research Affiliates found +2.8% a year before launch and +0.5% to +0.7% after, across 125 smart-beta indexes). This test measures the Ken 11 forward, on prices that did not exist when its rules were written.

## 2. The rules (frozen)

**The index.**
- **Eligible:** common stock of a US company, listed on a US exchange; no limited partnerships; no depositary receipts.
- **Excluded (the owner's choice):** Alphabet (GOOGL, GOOG), Tesla (TSLA) and Meta Platforms (META), by ticker and by company.
- **One company, one line:** share classes of one company (same SEC CIK) are ranked once, at the largest shares outstanding × closing price among its classes, and held through its most traded class (by dollar volume on the ranking date).
- **Ranked by full market value:** shares outstanding as last reported (EODHD's quarterly series), in the units of each listing's price, × the closing price. Berkshire Hathaway's count is converted to the units of each class (one Class A share is 1,500 Class B shares), because the vendor reports it in either unit.
- **Size:** the 11 largest. No buffer.
- **Schedule:** ranked at the close of the second Friday of March, June, September and December, from the 100 largest US listings by the vendor's market capitalization; rebalanced at the close of the third Friday, weighted by shares outstanding × that day's close. Between rebalances the weights drift with prices. If either Friday is not a trading day, the last trading day before it is used.
- **Returns:** total return, from EODHD's adjusted closes (dividends reinvested).

**The thermostat.**
- The share in stocks starts at min(1, 15.29% ÷ the index's volatility over the last 21 trading days), annualized with 252 days a year; the rest is cash, earning nothing.
- Between resets the share drifts with the index's return.
- Every 10 trading days from the start, at the close, the share is reset to min(1, 15.29% ÷ the last 21 trading days' volatility, including that day).
- 15.29% is the setting the website uses: it made the five-year backtest's realized volatility equal Ken's (15.56%).

**Costs and taxes.** The SEC fee on sales (0.21 bp), charged as 0.105 bp on all value traded at each reset. No commission (Schwab charges none through its API). Before taxes.

**Execution.** Every trade is assumed done at the closing price.

## 3. The start

- **Holdings:** the September 2026 quarter, ranked at the close of September 11, 2026 and rebalanced at the close of September 18, 2026: NVDA, AAPL, MSFT, AMZN, AVGO, MU, BRK-B, LLY, JPM, WMT and AMD, weighted by their shares outstanding as reported for June 30, 2026 (listed in `forward/run.py`). That ranking was made from the S&P 500's members (the store at hand); the 12th company (Visa) was $140 billion behind the 11th, so the wider US market would not have changed the list.
- **The track starts at 1.0 at the first close after the rules are frozen** (the `init` run records the date). The index's returns from September 18 to the start set the thermostat's first reading. The next ranking is December 11, 2026; the next rebalance December 18, 2026.

## 4. Benchmarks

- **SPY**, held fully invested, total return.
- **SPY plus cash at the same risk:** SPY with a fixed cash share, rebalanced daily, cash earning nothing, set so its volatility over the period equals the Ken 11's (the fair comparison; decisions, November 1, 2026).

## 5. Predictions

**The founder (F2, carried forward from pre-registration §18):** the constant-volatility personal index does not consistently lose to an index ETF held at the same volatility.

**Claude:**
- **P1.** After three years (the close of November 2029), the Ken 11's annual return exceeds SPY plus cash at the same risk by between 0 and 2 points: less than the backtest's 2.3, because backtested edges shrink once live.
- **P2.** Its worst drop over the three years is smaller than SPY's.
- **P3.** Its volatility over the three years is within 2 points of 15.3%.
- **P4.** In at least one of the first three calendar years it trails SPY fully invested (it holds cash, and the largest companies don't lead every year).

## 6. Reporting

- Every trading day, after the close, the track is updated from closing prices (`data/track.csv`: the index's level, the share in stocks, the Ken 11 and SPY, each starting at 1.0).
- At the end of every month, a report (`reports/`) and a new release, which Zenodo archives with its own DOI. Nothing is ever restated; a correction is a new, dated entry that explains itself.
- Formal evaluations against section 5 at one, three and five years.
- Only the track's own values are published, never the vendor's prices; anyone can recompute the track from these rules and any source of closing prices.

## 7. What this is not

Hypothetical performance of published rules, computed from closing prices: not an account, not an offer, not advice. It is the record the website's backtest has to live up to.
