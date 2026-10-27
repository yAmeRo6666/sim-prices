#!/usr/bin/env python3
"""Daily US-stock price feed for the Claude paper portfolio (runs on GitHub Actions).

Writes latest.json:
  {"generated_at": "<UTC ISO>", "final_through": "YYYY-MM-DD",
   "tickers": {"QQQ": [{"date", "open", "high", "low", "close", "adj"}, ... last 45 sessions], ...},
   "sources": {"QQQ": "yahoo" | "stooq"}, "missing": [...]}

Only bars dated <= final_through are written. final_through is today (New York time) once it is
16:20 or later on an NYSE trading day, otherwise the previous trading day — so an intraday bar
never leaves this script. Tickers: tickers.txt (portfolio, watch list) + universe.txt
(S&P 500 + Nasdaq-100, refreshed from Wikipedia on Mondays; the old list is kept on failure).
"""
import csv, datetime as dt, io, json, os, re, sys, time, urllib.request
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
KEEP = 45
TICKER_RE = re.compile(r"^[A-Z]{1,5}$")
CORE = ["QQQ", "SMH", "AVGO", "MU", "VOO"]
UA = {"User-Agent": "Mozilla/5.0 (price-feed; GitHub Actions)"}


# ---- NYSE calendar (same rules as the portfolio engine) ----
def _easter(y):
    a, b, c = y % 19, y // 100, y % 100
    d, e, f, g = b // 4, b % 4, (b + 8) // 25, (b - (b + 8) // 25 + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    return dt.date(y, (h + l - 7 * m + 114) // 31, (h + l - 7 * m + 114) % 31 + 1)


def _nth(y, mo, wd, n):
    d = dt.date(y, mo, 1)
    d += dt.timedelta((wd - d.weekday()) % 7)
    return d + dt.timedelta(7 * (n - 1))


def _last(y, mo, wd):
    d = dt.date(y + (mo == 12), mo % 12 + 1, 1) - dt.timedelta(1)
    return d - dt.timedelta((d.weekday() - wd) % 7)


def _obs(d):
    return d - dt.timedelta(1) if d.weekday() == 5 else d + dt.timedelta(1) if d.weekday() == 6 else d


def holidays(y):
    h = {_nth(y, 1, 0, 3), _nth(y, 2, 0, 3), _easter(y) - dt.timedelta(2), _last(y, 5, 0),
         _obs(dt.date(y, 6, 19)), _obs(dt.date(y, 7, 4)), _nth(y, 9, 0, 1), _nth(y, 11, 3, 4), _obs(dt.date(y, 12, 25))}
    if dt.date(y, 1, 1).weekday() != 5:
        h.add(_obs(dt.date(y, 1, 1)))
    return h


def is_trading(d):
    return d.weekday() < 5 and d not in holidays(d.year)


def prev_trading(d):
    d -= dt.timedelta(1)
    while not is_trading(d):
        d -= dt.timedelta(1)
    return d


def final_through(now_ny):
    d = now_ny.date()
    if is_trading(d) and now_ny.time() >= dt.time(16, 20):
        return d
    return prev_trading(d)


# ---- ticker lists ----
def read_list(path):
    if not os.path.exists(path):
        return []
    out = []
    for line in open(path, encoding="utf-8"):
        t = line.split("#")[0].strip().upper()
        if TICKER_RE.match(t):
            out.append(t)
    return out


def refresh_universe(path, today):
    if os.path.exists(path) and today.weekday() != 0:
        return
    try:
        import pandas as pd
        found = set()
        for url in ("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
                    "https://en.wikipedia.org/wiki/Nasdaq-100"):
            html = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30).read().decode("utf-8")
            for tb in pd.read_html(io.StringIO(html)):
                col = next((c for c in tb.columns if str(c).strip() in ("Symbol", "Ticker")), None)
                if col is not None and len(tb) >= 90:
                    found |= {str(x).strip().upper() for x in tb[col]}
        found = sorted(t for t in found if TICKER_RE.match(t))
        if len(found) >= 450:
            with open(path, "w", encoding="utf-8") as f:
                f.write("# S&P 500 + Nasdaq-100, refreshed " + today.isoformat() + "\n" + "\n".join(found) + "\n")
            print(f"universe refreshed: {len(found)} tickers")
    except Exception as e:  # keep the old list
        print(f"universe refresh failed, keeping the old list: {e}", file=sys.stderr)


# ---- sources ----
def r4(x):
    return round(float(x), 4)


def yahoo(tickers):
    import pandas as pd
    import yfinance as yf
    out = {}
    for i in range(0, len(tickers), 150):
        chunk = tickers[i:i + 150]
        for attempt in range(3):
            try:
                df = yf.download(chunk, period="4mo", interval="1d", auto_adjust=False, actions=False,
                                 group_by="ticker", threads=True, progress=False)
            except Exception as e:
                print(f"yahoo chunk {i}: {e}", file=sys.stderr)
                df = None
            got = 0
            if df is not None and len(df):
                multi = isinstance(df.columns, pd.MultiIndex)
                for t in chunk:
                    try:
                        sub = df[t] if multi else df
                    except KeyError:
                        continue
                    rows = []
                    for idx, r in sub.iterrows():
                        c = r.get("Close")
                        if c is None or pd.isna(c) or float(c) <= 0:
                            continue
                        a = r.get("Adj Close", c)
                        a = c if a is None or pd.isna(a) else a
                        rows.append({"date": idx.date().isoformat() if hasattr(idx, "date") else str(idx)[:10],
                                     "open": None if pd.isna(r.get("Open")) else r4(r.get("Open")),
                                     "high": None if pd.isna(r.get("High")) else r4(r.get("High")),
                                     "low": None if pd.isna(r.get("Low")) else r4(r.get("Low")),
                                     "close": r4(c), "adj": r4(a)})
                    if rows:
                        out[t] = rows
                        got += 1
            if got >= max(1, len(chunk) // 2):
                break
            time.sleep(30)
    return out


def stooq(t):
    url = f"https://stooq.com/q/d/l/?s={t.lower()}.us&i=d"
    try:
        text = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30).read().decode("utf-8")
    except Exception as e:
        print(f"stooq {t}: {e}", file=sys.stderr)
        return []
    rows = []
    for r in csv.DictReader(io.StringIO(text)):
        try:
            c = float(r["Close"])
            rows.append({"date": r["Date"], "open": r4(r["Open"]), "high": r4(r["High"]), "low": r4(r["Low"]),
                         "close": r4(c), "adj": r4(c)})
        except (KeyError, ValueError):
            pass
    return rows[-90:]


def main(now_ny=None):
    now_ny = now_ny or dt.datetime.now(NY)
    ft = final_through(now_ny).isoformat()
    refresh_universe("universe.txt", now_ny.date())
    tickers = list(dict.fromkeys(CORE + read_list("tickers.txt") + read_list("universe.txt")))
    data = yahoo(tickers)
    sources = {t: "yahoo" for t in data}
    for t in read_list("tickers.txt") + CORE:          # fallback for the names we really need
        if t not in data or data[t][-1]["date"] < ft:
            rows = stooq(t)
            if rows and (t not in data or rows[-1]["date"] > data[t][-1]["date"]):
                data[t], sources[t] = rows, "stooq (adj = close)"
    tick = {}
    for t, rows in data.items():
        rows = [r for r in rows if r["date"] <= ft]
        if rows:
            tick[t] = rows[-KEEP:]
    missing = sorted(t for t in tickers if t not in tick)
    stale_core = [t for t in CORE if t not in tick or tick[t][-1]["date"] != ft]
    feed = {"generated_at": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "final_through": ft, "tickers": tick, "sources": {t: sources.get(t) for t in tick},
            "missing": missing, "stale_core": stale_core}
    with open("latest.json", "w", encoding="utf-8") as f:
        json.dump(feed, f, separators=(",", ":"))
    print(f"final_through {ft}; {len(tick)} tickers; missing {len(missing)}; stale core {stale_core}")
    for t in CORE:
        if t in tick:
            print(t, tick[t][-1])


if __name__ == "__main__":
    main()
