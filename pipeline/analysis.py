"""Written market analysis shared by the dashboard and the PDF report."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from common import returns_frame, value_asof


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


# ---------------------------------------------------------------------------
# Per-product analysis (technical state, regime and written commentary)
# ---------------------------------------------------------------------------

GROUP_ORDER = ["Equities", "Crypto", "Metals", "FX", "Yields"]

GROUP_TITLE = {
    "Equities": "Equity indices",
    "Crypto": "Crypto",
    "Metals": "Metals",
    "FX": "Currencies",
    "Yields": "US Treasury yields",
}

GROUP_INTRO = {
    "Equities": (
        "The S&P 500 is the broad US market, the Dow Jones tilts to large industrial and "
        "value companies, and the Nasdaq Composite tilts to technology and growth. Together "
        "they show appetite for risk and the phase of the equity cycle."
    ),
    "Crypto": (
        "Bitcoin and Ethereum are the two largest crypto assets. They trade around the clock "
        "and tend to amplify swings in global liquidity and risk appetite."
    ),
    "Metals": (
        "Gold is the classic safe haven, silver mixes safe-haven and industrial demand, and "
        "copper is a read on global industrial growth."
    ),
    "FX": (
        "EUR/USD is the price of one euro in US dollars. A falling rate means a stronger "
        "dollar, which usually tightens global financial conditions."
    ),
    "Yields": (
        "US Treasury yields across maturities. Short yields follow expected policy rates, "
        "long yields follow growth and inflation expectations, and the gap between them "
        "(the curve) is a classic signal of the economic cycle."
    ),
}


def _num(v, nd=1, suffix="%", sign=True):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "n/a"
    fmt = f"{{:{'+' if sign else ''}.{nd}f}}"
    return fmt.format(v) + suffix


def _bp(v):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "n/a"
    return f"{v * 100:+.0f}bp"


def _price(v):
    return f"{v:,.4f}" if abs(v) < 10 else f"{v:,.2f}"


def _pct_back(s, days):
    s = s.dropna()
    base = value_asof(s, s.index[-1] - pd.Timedelta(days=days))
    if base is None or math.isnan(base) or base == 0:
        return math.nan
    return (float(s.iloc[-1]) / base - 1) * 100


def _abs_back(s, days):
    s = s.dropna()
    base = value_asof(s, s.index[-1] - pd.Timedelta(days=days))
    return float(s.iloc[-1]) - base if not math.isnan(base) else math.nan


def technicals(s, transform, group):
    """Trend, momentum and volatility state of one series."""
    s = s.dropna()
    if len(s) < 60:
        return None
    last_date = s.index[-1]
    last = float(s.iloc[-1])
    ma50 = float(s.tail(50).mean())
    ma200 = float(s.tail(200).mean()) if len(s) >= 200 else math.nan
    above50 = last > ma50
    above200 = last > ma200 if not math.isnan(ma200) else above50
    if above200 and above50:
        trend = "Uptrend"
    elif above200:
        trend = "Pullback within uptrend"
    elif above50:
        trend = "Rebound below the 200-day average"
    else:
        trend = "Downtrend"

    d = s.diff().tail(14)
    gain, loss = d.clip(lower=0).mean(), (-d.clip(upper=0)).mean()
    rsi = 100.0 if loss == 0 else 100 - 100 / (1 + gain / loss)

    year = s[s.index > last_date - pd.Timedelta(days=365)]
    span = year.max() - year.min()
    out = {
        "trend": trend,
        "above50": bool(above50),
        "above200": bool(above200),
        "ma50": ma50,
        "ma200": ma200,
        "pct_vs_ma200": (last / ma200 - 1) * 100 if not math.isnan(ma200) else math.nan,
        "rsi": float(rsi),
        "range_pos": float((last - year.min()) / span) if span > 0 else math.nan,
    }
    if transform == "log":
        rets = np.log(s).diff().dropna()
        ann = math.sqrt(365 if group == "Crypto" else 252)
        n1y = 365 if group == "Crypto" else 252
        out["vol30"] = float(rets.tail(30).std() * ann * 100)
        out["vol1y"] = float(rets.tail(n1y).std() * ann * 100)
        out["pct_3m"] = _pct_back(s, 90)
    else:
        out["abs_3m"] = _abs_back(s, 90)
    return out


def _regime(drawdown):
    if drawdown is None or math.isnan(drawdown):
        return "of unknown drawdown state"
    if drawdown >= -5:
        return "within 5% of its 1-year high"
    if drawdown >= -10:
        return "in a mild pullback (5-10% below its 1-year high)"
    if drawdown >= -20:
        return "in correction territory (10-20% below its 1-year high)"
    return "in bear-market territory (more than 20% below its 1-year high)"


def _describe(label, transform, sn, t):
    if transform == "log":
        text = (
            f"{label} closed at {_price(sn['level'])} ({_num(sn['pct_1d'])} on the day, "
            f"{_num(sn['pct_1m'])} over one month, {_num(t['pct_3m'])} over three). "
            f"Trend: {t['trend'].lower()}; the price is {_regime(sn['drawdown_1y'])}. "
        )
        rsi = t["rsi"]
        if rsi >= 70:
            text += f"RSI is {rsi:.0f}, which is overbought. "
        elif rsi <= 30:
            text += f"RSI is {rsi:.0f}, which is oversold. "
        else:
            text += f"RSI is {rsi:.0f}, a neutral reading. "
        ratio = t["vol30"] / t["vol1y"] if t["vol1y"] else math.nan
        if ratio >= 1.25:
            word = "well above"
        elif ratio <= 0.8:
            word = "below"
        else:
            word = "in line with"
        text += (
            f"Recent volatility ({t['vol30']:.0f}% annualised) is {word} its 1-year "
            f"average ({t['vol1y']:.0f}%)."
        )
        return text
    text = (
        f"{label} stands at {sn['level']:.2f}% ({_bp(sn['abs_1d'])} on the day, "
        f"{_bp(sn['abs_1m'])} over one month, {_bp(t['abs_3m'])} over three). "
        f"Trend: {t['trend'].lower()}. "
    )
    z = sn.get("zscore_1y")
    if z is not None and not math.isnan(z):
        if z >= 1.5:
            text += f"It is high against the past year (z-score {z:+.1f})."
        elif z <= -1.5:
            text += f"It is low against the past year (z-score {z:+.1f})."
        else:
            text += f"It is within its normal 1-year range (z-score {z:+.1f})."
    return text


def _paragraphs(group, frame, meta, snap, techs):
    keys = [k for k in meta if meta[k]["group"] == group and k in techs]
    names = lambda ks: ", ".join(meta[k]["label"] for k in ks)  # noqa: E731
    out = []

    if group in ("Equities", "Crypto", "Metals"):
        n = len(keys)
        up200 = [k for k in keys if techs[k]["above200"]]
        if len(up200) == n:
            out.append(f"All {n} instruments trade above their 200-day average, consistent with an intact primary uptrend.")
        elif not up200:
            out.append(f"None of the {n} instruments holds above its 200-day average, so the primary trend is down.")
        else:
            out.append(f"{len(up200)} of {n} instruments trade above their 200-day average ({names(up200)}); the rest are below it.")
        deepest = min(keys, key=lambda k: snap[k]["drawdown_1y"])
        out.append(f"The deepest drawdown from the 1-year high is {meta[deepest]['label']} ({_num(snap[deepest]['drawdown_1y'])}).")

    if group == "Equities" and "nasdaq" in snap and "dow" in snap:
        diff = snap["nasdaq"]["pct_1m"] - snap["dow"]["pct_1m"]
        lead = "outperformed" if diff >= 0 else "lagged"
        tilt = "growth and technology" if diff >= 0 else "value and large industrial names"
        out.append(f"Over one month the Nasdaq {lead} the Dow by {abs(diff):.1f} percentage points, so the market is favouring {tilt}.")

    if group == "Crypto" and "eth" in frame and "btc" in frame:
        ratio = (frame["eth"] / frame["btc"]).dropna()
        chg = _pct_back(ratio, 30)
        lead = "outperforming" if chg >= 0 else "underperforming"
        out.append(f"The ETH/BTC ratio moved {_num(chg)} over one month: Ethereum is {lead} Bitcoin. A falling ratio usually signals a defensive stance inside crypto.")

    if group == "Metals":
        if "gold" in frame and "silver" in frame:
            gs = (frame["gold"] / frame["silver"]).dropna()
            out.append(
                f"The gold/silver ratio is {gs.iloc[-1]:.1f} ({_num(_pct_back(gs, 30))} over one month). "
                "A rising ratio points to defensive positioning; a falling one to risk appetite."
            )
        if "copper" in frame and "gold" in frame:
            cg = (frame["copper"] / frame["gold"]).dropna()
            chg = _pct_back(cg, 90)
            read = "growth optimism" if chg >= 0 else "growth worries"
            out.append(f"The copper/gold ratio moved {_num(chg)} over three months, a read of {read}.")

    if group == "FX" and "eurusd" in techs:
        t, sn = techs["eurusd"], snap["eurusd"]
        side = "above" if t["pct_vs_ma200"] >= 0 else "below"
        dollar = "weakened" if sn["pct_1m"] >= 0 else "strengthened"
        out.append(
            f"EUR/USD trades {abs(t['pct_vs_ma200']):.1f}% {side} its 200-day average and moved {_num(sn['pct_1m'])} over one month, "
            f"meaning the dollar has {dollar} against the euro."
        )

    if group == "Yields" and all(k in frame for k in ("y10", "y2", "y3m")):
        s2s10 = (frame["y10"] - frame["y2"]).dropna()
        s3m10 = (frame["y10"] - frame["y3m"]).dropna()
        c = _abs_back(s2s10, 30)
        move10 = snap["y10"]["abs_1m"]
        if c > 0.05:
            shape = "steepening"
        elif c < -0.05:
            shape = "flattening"
        else:
            shape = "little changed"
        label = {
            ("steepening", True): "a bear steepener (long yields rising faster than short ones, often an inflation or term-premium signal)",
            ("steepening", False): "a bull steepener (short yields falling faster, typical when markets price rate cuts)",
            ("flattening", True): "a bear flattener (short rates leading the move, tightening expectations)",
            ("flattening", False): "a bull flattener (long yields falling faster, typical of growth worries)",
        }.get((shape, move10 >= 0))
        out.append(
            f"The 10Y-2Y spread is {_bp(s2s10.iloc[-1])} and the 10Y-3M spread is {_bp(s3m10.iloc[-1])}. "
            + ("An inverted curve (negative spread) has historically preceded recessions. " if s3m10.iloc[-1] < 0 else "The curve is not inverted. ")
            + (f"Over one month the curve has been {shape}" + (f": {label}." if label else "."))
        )
    return out


def _status(group, keys, techs, snap):
    if group == "Yields":
        move = snap["y10"]["abs_1m"] if "y10" in snap else math.nan
        if math.isnan(move):
            return "Unknown", "neutral"
        if move > 0.15:
            return "Yields rising", "neutral"
        if move < -0.15:
            return "Yields falling", "neutral"
        return "Yields stable", "neutral"
    keys = [k for k in keys if k in techs]
    if not keys:
        return "No data", "neutral"
    share = sum(techs[k]["trend"] in ("Uptrend", "Pullback within uptrend") for k in keys) / len(keys)
    if share >= 0.67:
        return "Uptrend", "up"
    if share <= 0.33:
        return "Downtrend", "down"
    return "Mixed", "neutral"


def product_analysis(frame, meta, snap):
    """Structured per-group commentary for the dashboard."""
    techs = {}
    for key, m in meta.items():
        t = technicals(frame[key], m["transform"], m["group"])
        if t is not None and key in snap:
            techs[key] = t

    groups = []
    for group in GROUP_ORDER:
        keys = [k for k in meta if meta[k]["group"] == group]
        if not keys:
            continue
        status, tone = _status(group, keys, techs, snap)
        items = []
        for k in keys:
            if k not in techs:
                continue
            t = techs[k]
            items.append({
                "key": k,
                "label": meta[k]["label"],
                "summary": _describe(meta[k]["label"], meta[k]["transform"], snap[k], t),
                **t,
            })
        groups.append({
            "group": group,
            "title": GROUP_TITLE[group],
            "intro": GROUP_INTRO[group],
            "status": status,
            "tone": tone,
            "paragraphs": _paragraphs(group, frame, meta, snap, techs),
            "items": items,
        })
    return groups
