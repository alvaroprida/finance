"""Compute the latest snapshot and evaluate the alert threshold table.

Writes docs/data/status.json, which the dashboard and the PDF both read.
"""
from __future__ import annotations

import json
import math
import operator

from analysis import observations, one_year_correlation
from common import STATUS_PATH, clean, load_rules, load_series, snapshot

OPS = {">": operator.gt, ">=": operator.ge, "<": operator.lt, "<=": operator.le}


def main() -> None:
    frame, meta, payload = load_series()
    snap = snapshot(frame)
    rules = load_rules()

    evaluated = []
    for rule in rules:
        if rule["op"] not in OPS:
            raise SystemExit(f"rule {rule['id']}: unknown op {rule['op']!r}")
        if rule["series"] not in meta:
            raise SystemExit(f"rule {rule['id']}: unknown series {rule['series']!r}")
        s = snap.get(rule["series"], {})
        value = s.get(rule["metric"])
        if value is None:
            raise SystemExit(f"rule {rule['id']}: unknown metric {rule['metric']!r}")
        has_value = value is not None and not math.isnan(value)
        triggered = has_value and OPS[rule["op"]](value, rule["threshold"])
        evaluated.append(
            {
                **rule,
                "series_label": meta[rule["series"]]["label"],
                "value": value if has_value else None,
                "triggered": bool(triggered),
            }
        )

    as_of = frame.dropna(how="all").index[-1].strftime("%Y-%m-%d")
    corr = one_year_correlation(frame, meta)
    status = {
        "generated_utc": payload["generated_utc"],
        "as_of": as_of,
        "snapshot": snap,
        "observations": observations(meta, snap, corr, evaluated),
        "rules": evaluated,
        "triggered_count": sum(r["triggered"] for r in evaluated),
    }
    STATUS_PATH.write_text(json.dumps(clean(status), indent=1))
    print(
        f"wrote {STATUS_PATH} — {len(evaluated)} rules, "
        f"{status['triggered_count']} triggered, as of {as_of}"
    )


if __name__ == "__main__":
    main()
