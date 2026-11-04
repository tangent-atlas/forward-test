# The Tangent Atlas forward tests

Public, dated records of two personal indexes, each run by rules frozen before its first day:

- **The Ken 11** (from November 2026): the personal index shown on [tangentatlas.com](https://www.tangentatlas.com/your-plan), built for one fictional customer. Rules: [PREREGISTRATION.md](PREREGISTRATION.md). Track: [data/track.csv](data/track.csv).
- **The Joe 10** (from November 2026): the generic model, the 10 largest US companies, Constant Weight, held at 15% volatility. Rules: [PREREGISTRATION-JOE10.md](PREREGISTRATION-JOE10.md). Track: [data/joe10.csv](data/joe10.csv).

The Ken 11 in detail:

- **The rules and predictions:** [PREREGISTRATION.md](PREREGISTRATION.md), archived on Zenodo as version 1.0 before the track began.
- **The track:** [data/track.csv](data/track.csv), updated after every US market close: the index's level, the share in stocks, and the Ken 11 and SPY, each starting at 1.0.
- **Monthly reports:** [reports/](reports/), each also a release that Zenodo archives with its own DOI.

In short, the Ken 11 holds the 11 largest US companies by full market value, leaving out Alphabet, Tesla and Meta, weighted by size and rebalanced quarterly. Every two weeks its cash is reset so its volatility stays at the level its owner chose. It is compared with SPY, and with SPY plus cash at the same risk.

## Check it yourself

The track is computed by [forward/](forward/) from closing prices and nothing else. With the rules and any source of daily closing prices, anyone can recompute every row. The code that runs each day is the code in this repository: see [.github/workflows/daily.yml](.github/workflows/daily.yml) and the run history under Actions.

```
python -m pytest            # the rules, on synthetic markets with known answers
EODHD_API_TOKEN=... python -m forward.run daily
```

## What this is not

Hypothetical performance of published rules, before taxes, computed from closing prices. It is not an account, not an offer to sell or buy anything, and not investment advice. Past and simulated results don't predict future ones.

## Licence

Apache License 2.0. Prices come from EODHD and are used under its licence; they are not redistributed here.
