# sim-prices

Public daily US-stock prices for a **paper** (simulated) portfolio. No account data, no keys.

- `fetch_prices.py` runs on GitHub Actions after the US close (see `.github/workflows/prices.yml`), downloads daily bars from Yahoo Finance (Stooq as a fallback for the names in `tickers.txt`) and writes `latest.json`.
- `latest.json`: `final_through` is the last date whose bars are final (today only after 16:20 New York time), `tickers` holds the last 45 sessions per ticker (`date, open, high, low, close, adj`).
- `tickers.txt`: portfolio and watch-list names. `sp500.csv` / `ndx.csv`: index members (ticker, name), refreshed from Wikipedia on Mondays; `universe.txt` is an older fallback list.
- `market.json` / `brief_tables.md`: computed market data (indices, yields, cross-asset, sectors, themes, technicals, S&P 500 / Nasdaq-100 breadth, top movers, watch groups from `brief_config.json`) for the daily market brief; a dated copy of the tables is kept in `tables/`. `market.json` also holds `screens` (one-day drops ≤ −8%, new and near 52-week closing lows among S&P 500 + Nasdaq-100 — the paper portfolio's candidate lists) and `thermo` (10-year yield, WTI, dollar, SMH−QQQ 1-month, % of S&P 500 above the 50-day line, VIX); `thermo_history.csv` keeps one `thermo` row per day.
- Each run merges a 1-year and a 1-month download (Yahoo's 1-year series can lag a day) and keeps every confirmed bar from the previous `latest.json`, so a flaky download never removes a day. Table cells without a bar for `final_through` read 暂无可靠数据（最新 MM-DD）. `run_log.txt` is the last run's output.
