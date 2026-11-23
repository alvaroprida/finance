# Market Analysis

A daily market dashboard and PDF report. A scheduled GitHub Action pulls
market data, evaluates alert thresholds and rebuilds a two-page PDF. GitHub
Pages serves the static dashboard from `docs/`.

## Layout

```
config/
  instruments.yml     series catalogue (source symbol, group, units, return transform)
  thresholds.yml      alert threshold table (metric, operator, value, message)
pipeline/
  common.py           shared paths, loaders and metric helpers
  fetch_data.py       Yahoo Finance + FRED -> docs/data/series.json
  alerts.py           snapshot + rule evaluation -> docs/data/status.json
  report.py           two-page PDF -> docs/reports/market-YYYY-MM-DD.pdf (+ latest.pdf)
docs/                 static front end (GitHub Pages root)
  index.html, app.js, style.css
  data/               generated daily
  reports/            generated daily
.github/workflows/daily-market.yml   runs everything every day at 22:30 UTC
```

## Series currently tracked

| Group    | Series                                                   |
|----------|----------------------------------------------------------|
| Equities | S&P 500, Dow Jones Industrial, Nasdaq Composite          |
| Crypto   | Bitcoin, Ethereum                                        |
| Metals   | Copper, gold, silver (COMEX front-month futures)         |
| FX       | EUR/USD (USD per 1 EUR)                                  |
| Yields   | US Treasury 3M, 2Y, 5Y, 10Y, 30Y; curve 10Y minus 3M     |

Add a series by appending an entry to `config/instruments.yml`. Add an alert
by appending a rule to `config/thresholds.yml`.

## Run locally

```bash
pip install -r pipeline/requirements.txt
cd pipeline
python fetch_data.py   # writes docs/data/series.json
python alerts.py       # writes docs/data/status.json
python report.py       # writes docs/reports/*.pdf
cd ../docs && python3 -m http.server 8000   # open http://localhost:8000
```

## Enable GitHub Pages

Repository Settings, then Pages: deploy from branch `main`, folder `/docs`.
The daily workflow only runs on the default branch, so merge this work into
`main` before it starts updating automatically. It can also be triggered by
hand from the Actions tab (`workflow_dispatch`).

## Notes

- Yields come from FRED and publish with a lag of about one business day.
  Each series shows its own last date.
- Correlations use only dates where every selected series has a value.
  Prices use log returns and yields use daily changes.
- Figures are informational and not investment advice.
