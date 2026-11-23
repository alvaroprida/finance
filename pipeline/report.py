"""Render the daily two-page market PDF into docs/reports/.

Reads docs/data/series.json and docs/data/status.json (run fetch_data.py and
alerts.py first). Output: docs/reports/market-YYYY-MM-DD.pdf and latest.pdf.
"""
from __future__ import annotations

import datetime as dt
import io
import math
import shutil

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from reportlab.lib import colors  # noqa: E402
from reportlab.lib.pagesizes import A4  # noqa: E402
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet  # noqa: E402
from reportlab.lib.units import mm  # noqa: E402
from reportlab.lib.utils import ImageReader  # noqa: E402
from reportlab.platypus import (  # noqa: E402
    Image,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from common import REPORTS_DIR, load_series, load_status, returns_frame, value_asof  # noqa: E402

TENORS = [("y3m", "3M"), ("y2", "2Y"), ("y5", "5Y"), ("y10", "10Y"), ("y30", "30Y")]
GREEN = colors.HexColor("#15803d")
RED = colors.HexColor("#b91c1c")
GRID = colors.HexColor("#d4d4d8")
HEAD = colors.HexColor("#18181b")


def fmt_level(v, unit):
    if v is None:
        return "—"
    if unit == "%":
        return f"{v:.2f}%"
    return f"{v:,.2f}"


def fmt_pct(v):
    return "—" if v is None else f"{v:+.1f}%"


def fmt_bp(v):
    return "—" if v is None else f"{v * 100:+.0f}bp"


def fmt_z(v):
    return "—" if v is None else f"{v:+.1f}"


def fig_image(fig, width_mm):
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", dpi=200)
    plt.close(fig)
    data = buf.getvalue()
    w, h = ImageReader(io.BytesIO(data)).getSize()
    width = width_mm * mm
    return Image(io.BytesIO(data), width=width, height=width * h / w)


def snapshot_table(meta, snap, styles_cell):
    header = ["Instrument", "Last", "1D", "1M", "1Y", "vs 1Y high", "1Y z"]
    rows = [header]
    signed_cols = {2, 3, 4}
    for key, m in meta.items():
        s = snap.get(key)
        if not s:
            continue
        if m["transform"] == "diff":
            row = [
                m["label"],
                fmt_level(s["level"], m["unit"]),
                fmt_bp(s["abs_1d"]),
                fmt_bp(s["abs_1m"]),
                fmt_bp(s["abs_1y"]),
                "—",
                fmt_z(s["zscore_1y"]),
            ]
        else:
            row = [
                m["label"],
                fmt_level(s["level"], m["unit"]),
                fmt_pct(s["pct_1d"]),
                fmt_pct(s["pct_1m"]),
                fmt_pct(s["pct_1y"]),
                fmt_pct(s["drawdown_1y"]),
                fmt_z(s["zscore_1y"]),
            ]
        rows.append(row)

    table = Table(rows, colWidths=[46 * mm, 26 * mm, 18 * mm, 18 * mm, 18 * mm, 24 * mm, 16 * mm], repeatRows=1)
    style = [
        ("FONT", (0, 0), (-1, -1), "Helvetica", 7.5),
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 7.5),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("BACKGROUND", (0, 0), (-1, 0), HEAD),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("LINEBELOW", (0, 1), (-1, -1), 0.25, GRID),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]
    for r, row in enumerate(rows[1:], start=1):
        for c in signed_cols:
            if row[c].startswith("+"):
                style.append(("TEXTCOLOR", (c, r), (c, r), GREEN))
            elif row[c].startswith("-"):
                style.append(("TEXTCOLOR", (c, r), (c, r), RED))
    table.setStyle(TableStyle(style))
    return table


def rebased_chart(frame, meta, snap_keys, asof):
    import matplotlib.dates as mdates

    start = asof - pd.Timedelta(days=365)
    fig, ax = plt.subplots(figsize=(7.4, 3.2))
    for k in snap_keys:
        if meta[k]["transform"] != "log":
            continue
        s = frame.loc[frame.index >= start, k].dropna()
        if s.empty:
            continue
        ax.plot(s.index, s / s.iloc[0] * 100, lw=1.1, label=meta[k]["label"])
    ax.axhline(100, color="#71717a", lw=0.6, ls="--")
    ax.set_ylabel("Rebased to 100", fontsize=7)
    ax.grid(alpha=0.25)
    ax.tick_params(labelsize=7)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %y"))
    ax.legend(fontsize=6.5, ncol=5, frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.1))
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    fig.tight_layout()
    return fig


def curve_chart(frame, asof):
    labels = [t[1] for t in TENORS]
    fig, ax = plt.subplots(figsize=(4.0, 3.0))
    for label, when in [
        ("Today", asof),
        ("1M ago", asof - pd.Timedelta(days=30)),
        ("1Y ago", asof - pd.Timedelta(days=365)),
    ]:
        ys = [value_asof(frame[k], when) for k, _ in TENORS]
        ax.plot(labels, ys, marker="o", ms=3, lw=1.3, label=label)
    ax.set_ylabel("Yield (%)", fontsize=7)
    ax.set_title("US Treasury curve", fontsize=8)
    ax.grid(alpha=0.25)
    ax.tick_params(labelsize=7)
    ax.legend(fontsize=6.5, frameon=False)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    fig.tight_layout()
    return fig


SHORT = {
    "sp500": "S&P500", "dow": "DJI", "nasdaq": "Nasdaq", "btc": "BTC", "eth": "ETH",
    "copper": "Copper", "gold": "Gold", "silver": "Silver", "eurusd": "EURUSD",
    "y3m": "3M", "y2": "2Y", "y5": "5Y", "y10": "10Y", "y30": "30Y", "spread_10y_3m": "10Y-3M",
}


def corr_chart(corr):
    labels = [SHORT.get(k, k) for k in corr.columns]
    n = len(labels)
    fig, ax = plt.subplots(figsize=(6.2, 5.4))
    im = ax.imshow(corr.values, cmap="RdBu_r", vmin=-1, vmax=1)
    ax.set_xticks(range(n))
    ax.set_yticks(range(n))
    ax.set_xticklabels(labels, rotation=60, ha="right", fontsize=6)
    ax.set_yticklabels(labels, fontsize=6)
    for i in range(n):
        for j in range(n):
            v = corr.values[i, j]
            ax.text(j, i, f"{v:.2f}", ha="center", va="center", fontsize=4.6,
                    color="white" if abs(v) > 0.6 else "black")
    ax.set_title("Correlation of daily returns, last 12 months", fontsize=8)
    fig.colorbar(im, ax=ax, fraction=0.046, pad=0.03)
    fig.tight_layout()
    return fig


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


def alerts_table(rules, body):
    rows = [["Status", "Instrument", "Rule", "Value*", "Threshold"]]
    ordered = sorted(rules, key=lambda r: (not r["triggered"], r["severity"] != "warning"))
    for r in ordered:
        val = "—" if r["value"] is None else f"{r['value']:.2f}"
        status = "TRIGGERED" if r["triggered"] else "ok"
        rows.append([
            status,
            r["series_label"],
            Paragraph(r["message"], body),
            val,
            f"{r['op']} {r['threshold']}",
        ])
    table = Table(rows, colWidths=[20 * mm, 30 * mm, 84 * mm, 18 * mm, 30 * mm], repeatRows=1)
    style = [
        ("FONT", (0, 0), (-1, -1), "Helvetica", 7),
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 7),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("BACKGROUND", (0, 0), (-1, 0), HEAD),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LINEBELOW", (0, 1), (-1, -1), 0.25, GRID),
        ("TOPPADDING", (0, 0), (-1, -1), 1.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
    ]
    for i, r in enumerate(ordered, start=1):
        if r["triggered"]:
            style += [("TEXTCOLOR", (0, i), (0, i), RED), ("FONT", (0, i), (0, i), "Helvetica-Bold", 7)]
        else:
            style += [("TEXTCOLOR", (0, i), (0, i), colors.HexColor("#71717a"))]
    table.setStyle(TableStyle(style))
    return table


def build(frame, meta, status, out_path):
    asof = pd.Timestamp(status["as_of"])
    snap = status["snapshot"]
    rules = status["rules"]

    ss = getSampleStyleSheet()
    body = ParagraphStyle("body", parent=ss["BodyText"], fontName="Helvetica", fontSize=7.5, leading=9.5)
    cell = ParagraphStyle("cell", parent=body, fontSize=7, leading=8.5)
    title = ParagraphStyle("title", parent=ss["Title"], fontName="Helvetica-Bold", fontSize=15,
                           leading=18, alignment=0, spaceAfter=1)
    sub = ParagraphStyle("sub", parent=body, textColor=colors.HexColor("#52525b"), fontSize=7.5)
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], fontName="Helvetica-Bold", fontSize=9.5,
                        leading=12, spaceBefore=5, spaceAfter=3)
    bullet = ParagraphStyle("bullet", parent=body, leftIndent=8, bulletIndent=0)
    foot = ParagraphStyle("foot", parent=body, fontSize=6.3, leading=7.5,
                          textColor=colors.HexColor("#71717a"))

    # Correlations over last 12 months across every series.
    keys = list(meta.keys())
    rets = returns_frame(frame, meta, keys, start=asof - pd.Timedelta(days=365))
    corr = rets.corr()

    story = [
        Paragraph(f"Daily Market Analysis — {asof.strftime('%d %b %Y')}", title),
        Paragraph(
            f"Data as of {status['as_of']} (latest close per series; yields follow FRED's publication lag). "
            f"Generated {status['generated_utc']}.",
            sub,
        ),
        Paragraph("Key observations", h2),
    ]
    for line in observations(meta, snap, corr, rules):
        story.append(Paragraph(line, bullet, bulletText="•"))
    story += [
        Paragraph("Snapshot", h2),
        snapshot_table(meta, snap, cell),
        Paragraph("Performance over one year, rebased to 100", h2),
        fig_image(rebased_chart(frame, meta, keys, asof), 180),
    ]
    story.append(PageBreak())
    story.append(Paragraph("Yield curve and correlations", h2))

    curve = fig_image(curve_chart(frame, asof), 78)
    heat = fig_image(corr_chart(corr), 100)
    story.append(Table([[curve, heat]], colWidths=[84 * mm, 100 * mm],
                       style=[("VALIGN", (0, 0), (-1, -1), "TOP"),
                              ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    story.append(Paragraph("Alert thresholds", h2))
    story.append(alerts_table(rules, cell))
    story.append(Spacer(1, 4))
    story.append(Paragraph(
        "*Value in the instrument's unit: yield and spread rules use percentage points "
        "(0.5 = 50bp). Automated summary of public market data (Yahoo Finance, FRED). "
        "Not investment advice. Correlations use returns on dates where all series traded; "
        "yields use daily changes.",
        foot,
    ))

    doc = SimpleDocTemplate(
        str(out_path), pagesize=A4,
        leftMargin=14 * mm, rightMargin=14 * mm, topMargin=12 * mm, bottomMargin=12 * mm,
        title=f"Daily Market Analysis {status['as_of']}",
    )
    doc.build(story)


def main():
    frame, meta, _ = load_series()
    status = load_status()
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    dated = REPORTS_DIR / f"market-{status['as_of']}.pdf"
    build(frame, meta, status, dated)
    shutil.copyfile(dated, REPORTS_DIR / "latest.pdf")
    print(f"wrote {dated} and latest.pdf")


if __name__ == "__main__":
    main()
