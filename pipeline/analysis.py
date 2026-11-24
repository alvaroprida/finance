"""Written market analysis shared by the dashboard and the PDF report."""
from __future__ import annotations

import math

import pandas as pd

from common import returns_frame


def one_year_correlation(frame, meta):
    """Correlation of daily returns over the last 12 months, all series."""
    keys = list(meta.keys())
    asof = frame.dropna(how="all").index[-1]
    rets = returns_frame(frame, meta, keys, start=asof - pd.Timedelta(days=365))
    return rets.corr()


def observations(meta, snap, corr, rules):
    obs = []
    price_keys = [k for k in snap if meta[k]["transform"] == "log"]

    movers = sorted(
        ((k, snap[k]["pct_1m"]) for k in price_keys if not math.isnan(snap[k]["pct_1m"])),
        key=lambda t: -abs(t[1]),
    )[:3]
    obs.append(
        "Largest 1-month moves: "
        + ", ".join(f"{meta[k]['label']} {v:+.1f}%" for k, v in movers)
        + "."
    )

    deep = [(meta[k]["label"], snap[k]["drawdown_1y"]) for k in price_keys
            if snap[k]["drawdown_1y"] <= -10]
    if deep:
        obs.append(
            "More than 10% below 1-year high: "
            + ", ".join(f"{name} ({v:.0f}%)" for name, v in deep) + "."
        )
    else:
        obs.append("No price series is more than 10% below its 1-year high.")

    sp = snap.get("spread_10y_3m")
    if sp:
        state = "inverted" if sp["level"] < 0 else "positive"
        obs.append(
            f"10Y minus 3M spread at {sp['level'] * 100:+.0f}bp ({state}), "
            f"{sp['abs_1m'] * 100:+.0f}bp over one month."
        )

    keys = list(corr.columns)
    pairs = [(keys[i], keys[j], corr.values[i, j])
             for i in range(len(keys)) for j in range(i + 1, len(keys))]
    pos = sorted(pairs, key=lambda t: -t[2])[:2]
    neg = sorted(pairs, key=lambda t: t[2])[:2]
    obs.append(
        "Highest 1Y co-movement: "
        + "; ".join(f"{meta[a]['label']} / {meta[b]['label']} ({r:+.2f})" for a, b, r in pos)
        + "."
    )
    obs.append(
        "Strongest inverse relationships: "
        + "; ".join(f"{meta[a]['label']} / {meta[b]['label']} ({r:+.2f})" for a, b, r in neg)
        + "."
    )

    triggered = [r for r in rules if r["triggered"]]
    obs.append(f"{len(triggered)} of {len(rules)} alert rules triggered today.")
    return obs
