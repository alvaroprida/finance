# Pipeline (developer notes)

Daily job that powers the market dashboard in `docs/`.

```
config/instruments.yml   series catalogue (source symbol, group, units, return transform)
config/thresholds.yml    alert threshold table (metric, operator, value, message)
pipeline/fetch_data.py   Yahoo Finance + FRED -> docs/data/series.json
pipeline/alerts.py       snapshot, alert rules and written analysis -> docs/data/status.json
pipeline/analysis.py     correlation and observation logic shared by dashboard and PDF
pipeline/report.py       two-page PDF -> docs/reports/market-YYYY-MM-DD.pdf (+ latest.pdf)
.github/workflows/daily-market.yml   runs everything every day at 22:30 UTC
```

Run locally:

```bash
pip install -r pipeline/requirements.txt
cd pipeline
python fetch_data.py   # writes docs/data/series.json
python alerts.py       # writes docs/data/status.json
python report.py       # writes docs/reports/*.pdf
cd ../docs && python3 -m http.server 8000   # open http://localhost:8000
```

Add a series by appending to `config/instruments.yml`. Add an alert by appending to `config/thresholds.yml`.

Notes:
- Yields come from FRED and publish with about a one-business-day lag.
- Correlations use only dates where every selected series traded.
- Prices use log returns; yields use daily changes.
