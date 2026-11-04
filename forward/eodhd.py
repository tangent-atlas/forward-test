"""EODHD, the one data source. The API token comes from the EODHD_API_TOKEN environment variable (a GitHub secret in the
workflow); it is never written to a file or a log. Raw vendor data is used in memory only: the repository publishes the
track's own values, never EODHD's prices."""
from __future__ import annotations

import datetime as dt
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://eodhd.com/api/"


def _get(path: str, **params) -> object:
    token = os.environ.get("EODHD_API_TOKEN")
    if not token:
        raise RuntimeError("EODHD_API_TOKEN is not set.")
    query = urllib.parse.urlencode({**params, "api_token": token, "fmt": "json"})
    url = BASE + path + "?" + query
    for attempt in range(6):
        try:
            with urllib.request.urlopen(url, timeout=60) as response:
                return json.load(response)
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and attempt < 5:
                time.sleep(2 ** (attempt + 1))
                continue
            raise RuntimeError(f"EODHD {path} returned {e.code}.") from None   # the URL holds the token: never shown


def symbol(code: str) -> str:
    return code + ".US"


def daily(code: str, start: dt.date, end: dt.date) -> dict[dt.date, dict]:
    """Closing price, adjusted close (dividends and splits) and volume, by date."""
    rows = _get("eod/" + symbol(code), **{"from": start.isoformat(), "to": end.isoformat()})
    return {dt.date.fromisoformat(r["date"]): {"close": float(r["close"]), "adjusted": float(r["adjusted_close"]),
                                              "volume": float(r.get("volume") or 0)} for r in rows}


def largest(limit: int = 100) -> list[str]:
    """The largest US listings by the vendor's market capitalization: the pool the ranking draws from."""
    rows = _get("screener", sort="market_capitalization.desc", filters=json.dumps([["exchange", "=", "us"]]),
                limit=limit, offset=0)
    return [r["code"].replace(".", "-") for r in rows.get("data", [])]


def company(code: str, on: dt.date) -> dict:
    """Name, type, country, exchange, CIK, and shares outstanding as last reported on or before `on`."""
    data = _get("fundamentals/" + symbol(code), filter="General,outstandingShares")
    general = data.get("General") or {}
    reported = []
    for row in ((data.get("outstandingShares") or {}).get("quarters") or {}).values():
        try:
            day = dt.date.fromisoformat(row["dateFormatted"])
        except (KeyError, ValueError):
            continue
        if day <= on and row.get("shares"):
            reported.append((day, float(row["shares"])))
    return {
        "name": general.get("Name") or "",
        "type": general.get("Type") or "",
        "country": general.get("CountryISO") or "",
        "exchange": general.get("Exchange") or "",
        "cik": str(general.get("CIK") or "").lstrip("0"),
        "shares": max(reported)[1] if reported else 0.0,
    }
