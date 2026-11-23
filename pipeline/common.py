"""Shared paths, config loading and metric helpers for the market pipeline."""
from __future__ import annotations

import json
import math
import pathlib

import numpy as np
import pandas as pd
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "docs" / "data"
REPORTS_DIR = ROOT / "docs" / "reports"
SERIES_PATH = DATA_DIR / "series.json"
STATUS_PATH = DATA_DIR / "status.json"
START = "2000-01-01"


def load_instruments():
    return yaml.safe_load((CONFIG_DIR / "instruments.yml").read_text())["series"]


def load_rules():
    return yaml.safe_load((CONFIG_DIR / "thresholds.yml").read_text())["rules"]


def load_series():
    """Return (frame, meta, payload). frame has one float column per series key."""
    payload = json.loads(SERIES_PATH.read_text())
    frame = pd.DataFrame(
        {key: s["values"] for key, s in payload["series"].items()},
        index=pd.to_datetime(payload["dates"]),
        dtype=float,
    )
    meta = {
        key: {k: v for k, v in s.items() if k != "values"}
        for key, s in payload["series"].items()
    }
    return frame, meta, payload


def load_status():
    return json.loads(STATUS_PATH.read_text())


def value_asof(s: pd.Series, when: pd.Timestamp) -> float:
    """Last non-null value on or before `when` (NaN if none)."""
    s = s[s.index <= when].dropna()
    return float(s.iloc[-1]) if len(s) else math.nan


def pct(a, b) -> float:
    if b is None or pd.isna(a) or pd.isna(b) or b == 0:
        return math.nan
    return (a / b - 1) * 100


def snapshot(frame: pd.DataFrame) -> dict:
    """Latest value and standard changes for every series with data."""
    out = {}
    for key in frame.columns:
        s = frame[key].dropna()
        if s.empty:
            continue
        last_date = s.index[-1]
        last = float(s.iloc[-1])
        prev = float(s.iloc[-2]) if len(s) > 1 else math.nan

        def back(days, s=s, last_date=last_date):
            return value_asof(s, last_date - pd.Timedelta(days=days))

        w1, m1, y1_ago = back(7), back(30), back(365)
        window = s[s.index > last_date - pd.Timedelta(days=365)]
        std = window.std()
        out[key] = {
            "last_date": last_date.strftime("%Y-%m-%d"),
            "level": last,
            "pct_1d": pct(last, prev),
            "pct_1w": pct(last, w1),
            "pct_1m": pct(last, m1),
            "pct_1y": pct(last, y1_ago),
            "abs_1d": last - prev,
            "abs_1m": last - m1,
            "abs_1y": last - y1_ago,
            "drawdown_1y": pct(last, window.max()),
            "zscore_1y": float((last - window.mean()) / std)
            if len(window) > 2 and std > 0
            else math.nan,
        }
    return out


def returns_frame(frame: pd.DataFrame, meta: dict, keys: list, start=None) -> pd.DataFrame:
    """Daily returns on dates where every key has a value.

    Matches the front-end calculation in docs/app.js.
    """
    sub = frame[keys]
    if start is not None:
        sub = sub[sub.index >= start]
    sub = sub.dropna()
    out = {}
    for k in keys:
        if meta[k]["transform"] == "log":
            out[k] = np.log(sub[k]).diff()
        else:
            out[k] = sub[k].diff()
    return pd.DataFrame(out).dropna()


def clean(obj):
    """Recursively replace NaN/inf with None so the output is valid JSON."""
    if isinstance(obj, dict):
        return {k: clean(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [clean(v) for v in obj]
    if isinstance(obj, float) and not math.isfinite(obj):
        return None
    return obj
