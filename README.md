# sim-prices

Public daily US-stock prices for a **paper** (simulated) portfolio. No account data, no keys.

- `fetch_prices.py` runs on GitHub Actions after the US close (see `.github/workflows/prices.yml`), downloads daily bars from Yahoo Finance (Stooq as a fallback for the names in `tickers.txt`) and writes `latest.json`.
- `latest.json`: `final_through` is the last date whose bars are final (today only after 16:20 New York time), `tickers` holds the last 45 sessions per ticker (`date, open, high, low, close, adj`).
- `tickers.txt`: portfolio and watch-list names; `universe.txt`: S&P 500 + Nasdaq-100, refreshed weekly.
- `market.json` / `brief_tables.md`: computed market data (indices, yields, cross-asset, sectors, themes, technicals, S&P 500 / Nasdaq-100 breadth, top movers, watch groups from `brief_config.json`) for the daily market brief; a dated copy of the tables is kept in `tables/`.
