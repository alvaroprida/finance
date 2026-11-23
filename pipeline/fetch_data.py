"""Download daily history for every series in config/instruments.yml.

Writes docs/data/series.json: all series aligned on the union of dates, with
null where a series did not trade or publish. Any source that keeps failing
after retries stops the run, so the last good files stay committed.
"""
from __future__ import annotations

import datetime as dt
import io
import json
import sys
import time

import pandas as pd
import requests
import yfinance as yf

from common import DATA_DIR, SERIES_PATH, START, load_instruments

FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv"


def with_retries(label, fn, attempts=4):
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - retry any source error
            print(f"[{label}] attempt {attempt} failed: {exc}", file=sys.stderr)
            if attempt == attempts:
                raise
            time.sleep(10 * attempt)


def yahoo_close(symbol: str) -> pd.Series:
    hist = yf.Ticker(symbol).history(start=START, auto_adjust=True)
    if hist.empty:
        raise RuntimeError("no rows returned")
    close = hist["Close"].copy()
    idx = pd.DatetimeIndex(close.index)
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    close.index = idx.normalize()
    return close[~close.index.duplicated(keep="last")].astype(float)


def fred_series(code: str) -> pd.Series:
    resp = requests.get(FRED_CSV, params={"id": code, "cosd": START}, timeout=60)
    resp.raise_for_status()
    df = pd.read_csv(io.StringIO(resp.text), index_col=0, parse_dates=True, na_values=".")
    s = df.iloc[:, 0].astype(float)
    s.index = pd.DatetimeIndex(s.index).normalize()
    return s.dropna()


def main() -> None:
    instruments = load_instruments()
    raw: dict[str, pd.Series] = {}

    for inst in instruments:
        key, source = inst["key"], inst["source"]
        if source == "yahoo":
            raw[key] = with_retries(key, lambda sym=inst["symbol"]: yahoo_close(sym))
        elif source == "fred":
            raw[key] = with_retries(key, lambda sym=inst["symbol"]: fred_series(sym))

    for inst in instruments:
        if inst["source"] == "derived":
            a, b = inst["minus"]
            raw[inst["key"]] = raw[a] - raw[b]

    frame = pd.DataFrame(raw).sort_index()
    frame = frame[frame.index >= pd.Timestamp(START)].dropna(how="all")
    if frame.empty:
        raise SystemExit("no data after filtering; refusing to overwrite series.json")

    series_out = {}
    for inst in instruments:
        col = frame[inst["key"]]
        if col.notna().sum() == 0:
            raise SystemExit(f"{inst['key']} has no observations")
        series_out[inst["key"]] = {
            "label": inst["label"],
            "group": inst["group"],
            "unit": inst["unit"],
            "transform": inst["transform"],
            "source": inst["source"],
            "values": [None if pd.isna(v) else round(float(v), 6) for v in col],
        }

    payload = {
        "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "as_of": frame.index[-1].strftime("%Y-%m-%d"),
        "dates": [d.strftime("%Y-%m-%d") for d in frame.index],
        "series": series_out,
    }
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SERIES_PATH.write_text(json.dumps(payload, separators=(",", ":")))
    print(
        f"wrote {SERIES_PATH} — {len(frame)} dates, {len(series_out)} series, "
        f"as of {payload['as_of']}"
    )


if __name__ == "__main__":
    main()
