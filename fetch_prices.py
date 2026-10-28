#!/usr/bin/env python3
"""Daily US-stock price feed for the Claude paper portfolio (runs on GitHub Actions).

Outputs (all from Yahoo Finance; Stooq as a fallback for the names in tickers.txt):
  latest.json      {"generated_at", "final_through", "tickers": {T: [{"date","open","high","low","close","adj"}, ... last 45]},
                    "sources", "missing", "stale_core"} — read by the portfolio engine (--feed mode).
  market.json      computed market data for the daily market brief: indices, rates, cross-asset, sectors, themes,
                    technicals, breadth (S&P 500 / Nasdaq-100), top movers, watch groups (see brief_config.json).
  brief_tables.md  the same numbers as ready-made Chinese markdown tables.

Only bars dated <= final_through are used. final_through is today (New York time) once it is 16:20 or later on an
NYSE trading day, otherwise the previous trading day — so an intraday bar never leaves this script.
Ticker universe: tickers.txt + brief_config.json names + S&P 500 + Nasdaq-100 (sp500.csv / ndx.csv, refreshed from
Wikipedia on Mondays or when missing; the old lists are kept on failure).
"""
import csv, datetime as dt, io, json, math, os, re, sys, time, urllib.request
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
        t = line.split("#")[0].split(",")[0].strip().upper()
        if TICKER_RE.match(t):
            out.append(t)
    return out


def read_names(path):
    names = {}
    if os.path.exists(path):
        for r in csv.reader(open(path, encoding="utf-8")):
            if r and TICKER_RE.match(r[0].strip()):
                names[r[0].strip()] = r[1].strip() if len(r) > 1 else ""
    return names


def colname(c):
    c = " ".join(str(x) for x in c) if isinstance(c, tuple) else str(c)
    return re.sub(r"\[.*?\]", "", c).strip()


def refresh_universe(today):
    if os.path.exists("sp500.csv") and os.path.exists("ndx.csv") and today.weekday() != 0:
        return
    try:
        import pandas as pd
        sources = (("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies", "sp500.csv", 480),
                   ("https://en.wikipedia.org/wiki/Nasdaq-100", "ndx.csv", 95),
                   ("https://en.wikipedia.org/wiki/List_of_Nasdaq-100_companies", "ndx.csv", 95),
                   ("https://en.wikipedia.org/wiki/List_of_NASDAQ-100_companies", "ndx.csv", 95))
        done = set()
        for url, path, minimum in sources:
            if path in done:
                continue
            try:
                html = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30).read().decode("utf-8")
            except Exception as e:
                print(f"{path}: {url} failed: {e}")
                continue
            best, seen = {}, []
            for tb in pd.read_html(io.StringIO(html)):
                cols = {c: colname(c) for c in tb.columns}
                seen.append((len(tb), list(cols.values())[:4]))
                tcol = next((c for c, n in cols.items() if n.split(" ")[0] in ("Symbol", "Ticker")), None)
                ncol = next((c for c, n in cols.items() if n.split(" ")[0] in ("Security", "Company", "Name")), None)
                if tcol is None or len(tb) < minimum:
                    continue
                for _, row in tb.iterrows():
                    t = str(row[tcol]).strip().upper()
                    if TICKER_RE.match(t):
                        best[t] = str(row[ncol]).strip() if ncol is not None else ""
            if len(best) >= minimum:
                with open(path, "w", encoding="utf-8", newline="") as f:
                    w = csv.writer(f)
                    for t in sorted(best):
                        w.writerow([t, best[t]])
                print(f"{path}: {len(best)} tickers from {url}")
                done.add(path)
            else:
                print(f"{path}: {url} gave only {len(best)} tickers; tables seen {seen[:6]}")
    except Exception as e:
        print(f"universe refresh failed, keeping the old lists: {e}", file=sys.stderr)


# ---- sources ----
def r4(x):
    return round(float(x), 4)


def yahoo(symbols, period="1y"):
    import warnings
    warnings.filterwarnings("ignore")
    import pandas as pd
    import yfinance as yf
    out = {}
    for i in range(0, len(symbols), 120):
        chunk = symbols[i:i + 120]
        for attempt in range(3):
            try:
                df = yf.download(chunk, period=period, interval="1d", auto_adjust=False, actions=False,
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
                        v = r.get("Volume")
                        rows.append({"date": idx.date().isoformat() if hasattr(idx, "date") else str(idx)[:10],
                                     "open": None if pd.isna(r.get("Open")) else r4(r.get("Open")),
                                     "high": None if pd.isna(r.get("High")) else r4(r.get("High")),
                                     "low": None if pd.isna(r.get("Low")) else r4(r.get("Low")),
                                     "close": r4(c), "adj": r4(a),
                                     "volume": None if v is None or pd.isna(v) else int(v)})
                    if rows:
                        out[t] = rows
                        got += 1
            if got >= max(1, len(chunk) // 2):
                break
            time.sleep(30)
    retry = [t for t in symbols if t not in out]
    if retry and len(retry) <= 40 and not getattr(yahoo, "_retrying", False):
        yahoo._retrying = True                          # e.g. "database is locked" from the threaded download
        try:
            time.sleep(5)
            out.update(yahoo(retry, period))
        finally:
            yahoo._retrying = False
    return out


def merge_rows(*lists):
    """Merge bar lists by date; later lists win field by field (None never overwrites a value)."""
    by = {}
    for rows in lists:
        for r in rows or []:
            cur = by.setdefault(r["date"], {})
            cur.update({k: v for k, v in r.items() if v is not None})
    return [by[d] for d in sorted(by)]


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
                         "close": r4(c), "adj": r4(c), "volume": int(float(r.get("Volume") or 0)) or None})
        except (KeyError, ValueError):
            pass
    return rows[-260:]


# ---- indicators ----
def sma(xs, n):
    return sum(xs[-n:]) / n if len(xs) >= n else None


def ema_series(xs, n):
    k, out = 2 / (n + 1), []
    for x in xs:
        out.append(x if not out else out[-1] + k * (x - out[-1]))
    return out


def rsi(xs, n=14):
    if len(xs) <= n:
        return None
    gains = [max(0.0, xs[i] - xs[i - 1]) for i in range(1, len(xs))]
    losses = [max(0.0, xs[i - 1] - xs[i]) for i in range(1, len(xs))]
    ag, al = sum(gains[:n]) / n, sum(losses[:n]) / n
    for g, l in zip(gains[n:], losses[n:]):
        ag, al = (ag * (n - 1) + g) / n, (al * (n - 1) + l) / n
    return 100.0 if al == 0 else 100 - 100 / (1 + ag / al)


def pct(a, b):
    return None if a is None or b in (None, 0) else a / b - 1


def stats(rows):
    """Indicators for one symbol from its daily rows (oldest → newest, all final)."""
    if len(rows) < 2:
        return None
    c = [r["close"] for r in rows]
    last, prev = rows[-1], rows[-2]
    vols = [r.get("volume") or 0 for r in rows]
    hi = [r.get("high") or r["close"] for r in rows]
    lo = [r.get("low") or r["close"] for r in rows]
    s = {"date": last["date"], "close": last["close"], "prev": prev["close"], "high": last.get("high"), "low": last.get("low"),
         "chg1d": pct(c[-1], c[-2]), "chg5d": pct(c[-1], c[-6]) if len(c) > 5 else None,
         "chg1m": pct(c[-1], c[-22]) if len(c) > 21 else None,
         "vol_ratio": (vols[-1] / (sum(vols[-21:-1]) / 20)) if len(vols) > 21 and sum(vols[-21:-1]) > 0 and vols[-1] else None}
    for n in (20, 50, 100, 200):
        m = sma(c, n)
        s[f"ma{n}"] = m
        s[f"vs_ma{n}"] = pct(c[-1], m)
    s["rsi14"] = rsi(c[-120:])
    if len(c) >= 35:
        e12, e26 = ema_series(c, 12), ema_series(c, 26)
        macd = [a - b for a, b in zip(e12, e26)]
        sig = ema_series(macd, 9)
        s["macd"], s["macd_signal"] = macd[-1], sig[-1]
    window = rows[-252:]
    s["hi52"] = max(r.get("high") or r["close"] for r in window)
    s["lo52"] = min(r.get("low") or r["close"] for r in window)
    prior_hi = max(hi[-252:-1]) if len(hi) > 1 else None
    prior_lo = min(lo[-252:-1]) if len(lo) > 1 else None
    s["new_high"] = bool(prior_hi and (last.get("high") or last["close"]) > prior_hi and len(rows) >= 120)
    s["new_low"] = bool(prior_lo and (last.get("low") or last["close"]) < prior_lo and len(rows) >= 120)
    s["hi20"], s["lo20"] = max(hi[-20:]), min(lo[-20:])
    return s


def breadth(members, st, ft):
    m = [st[t] for t in members if t in st and st[t] and st[t]["date"] == ft]
    if not m:
        return None
    out = {"n": len(m), "adv": sum(1 for s in m if (s["chg1d"] or 0) > 0), "dec": sum(1 for s in m if (s["chg1d"] or 0) < 0),
           "new_highs": sum(1 for s in m if s["new_high"]), "new_lows": sum(1 for s in m if s["new_low"])}
    out["unch"] = out["n"] - out["adv"] - out["dec"]
    for n in (20, 50, 100, 200):
        have = [s for s in m if s.get(f"ma{n}")]
        out[f"above_ma{n}"] = (sum(1 for s in have if s["close"] > s[f"ma{n}"]) / len(have)) if have else None
    return out


def rnd(s):
    if s is None:
        return None
    return {k: (round(v, 6) if isinstance(v, float) else v) for k, v in s.items()}


# ---- brief tables (Chinese markdown) ----
def fp(v, d=2):
    return "—" if v is None else f"{v:,.{d}f}"


def fpct(v, d=2):
    return "—" if v is None else f"{v * 100:+.{d}f}%"


def fpos(v):
    return "—" if v is None else ("上方" if v > 0 else "下方") + f" {abs(v) * 100:.1f}%"


def render(market, cfg, names):
    allst, lab, ft = market["assets"], cfg["labels"], market["final_through"]
    st = {t: s for t, s in allst.items() if s.get("date") == ft}    # a stale bar is never shown as today's

    def na(t):
        s = allst.get(t)
        return f"暂无可靠数据（最新 {s['date'][5:]}）" if s else "暂无可靠数据"
    L = [f"# 行情数据表｜{market['final_through']}",
         f"数据：Yahoo Finance，由 GitHub Actions 在 {market['generated_at']} 生成；均为收盘后确认的日线数据。",
         "宽度只统计标普500 和纳指100 成分股（不是 NYSE/Nasdaq 全市场）。", ""]

    def name(t):
        return lab.get(t) or names.get(t) or t

    L += ["## 表1 大盘", "| 指数 | 收盘 | 涨跌 | 日内高/低 | 量比 | 20日线 | 50日线 | 200日线 | RSI | 状态 |", "|---|---|---|---|---|---|---|---|---|---|"]
    for t in cfg["indices"]:
        s = st.get(t)
        if not s:
            L.append(f"| {name(t)} | {na(t)} |||||||||")
            continue
        tag = "52周新高" if s["new_high"] else ("52周新低" if s["new_low"] else "")
        L.append(f"| {name(t)} ({t}) | {fp(s['close'])} | {fpct(s['chg1d'])} | {fp(s['high'])}/{fp(s['low'])} | "
                 f"{fp(s['vol_ratio'])} | {fpos(s['vs_ma20'])} | {fpos(s['vs_ma50'])} | {fpos(s['vs_ma200'])} | {fp(s['rsi14'], 0)} | {tag} |")
    L += ["", "## 表2 美债收益率（%）", "| 期限 | 最新 | 日变化 | 5日变化 |", "|---|---|---|---|"]
    for t in cfg["rates"]:
        s = st.get(t)
        if s:
            five = None if s.get("chg5d") is None else s["close"] - s["close"] / (1 + s["chg5d"])
            L.append(f"| {name(t)} | {fp(s['close'], 3)} | {(s['close'] - s['prev']) * 100:+.1f}bp | {'—' if five is None else f'{five * 100:+.1f}bp'} |")
        else:
            L.append(f"| {name(t)} | {na(t)} | | |")
    y2, y10, y30 = (st.get(k) for k in ("US2Y", "US10Y", "US30Y"))
    if y2 and y10:
        L.append(f"| 2Y-10Y 利差 | {(y10['close'] - y2['close']) * 100:+.0f}bp | {((y10['close'] - y10['prev']) - (y2['close'] - y2['prev'])) * 100:+.1f}bp | |")
    if y10 and y30:
        L.append(f"| 10Y-30Y 利差 | {(y30['close'] - y10['close']) * 100:+.0f}bp | {((y30['close'] - y30['prev']) - (y10['close'] - y10['prev'])) * 100:+.1f}bp | |")
    L += ["", "## 表3 美元、黄金、原油、加密", "| 资产 | 最新 | 1日 | 5日 | 1月 |", "|---|---|---|---|---|"]
    for t in cfg["cross_asset"]:
        s = st.get(t)
        L.append(f"| {name(t)} | {fp(s['close'])} | {fpct(s['chg1d'])} | {fpct(s['chg5d'])} | {fpct(s['chg1m'])} |" if s else f"| {name(t)} | {na(t)} | | | |")
    spy = st.get("SPY") or {}
    rows = []
    for zh, t in cfg["sectors"].items():
        s = st.get(t)
        if s:
            rows.append((s["chg1d"] or 0, zh, t, s))
    rows.sort(reverse=True)
    L += ["", "## 表4 标普十一板块（按当日涨跌排序）", "| 排名 | 板块 | ETF | 1日 | 5日 | 1月 | 相对 SPY（1日） |", "|---|---|---|---|---|---|---|"]
    for i, (_, zh, t, s) in enumerate(rows, 1):
        rel = None if spy.get("chg1d") is None or s["chg1d"] is None else s["chg1d"] - spy["chg1d"]
        L.append(f"| {i} | {zh} | {t} | {fpct(s['chg1d'])} | {fpct(s['chg5d'])} | {fpct(s['chg1m'])} | {fpct(rel)} |")
    L += ["", "## 表5 主题与风格", "| 主题 | ETF | 1日 | 5日 | 1月 |", "|---|---|---|---|---|"]
    for zh, ts in cfg["themes"].items():
        for t in ts:
            s = st.get(t)
            L.append(f"| {zh} | {t} | {fpct(s['chg1d'])} | {fpct(s['chg5d'])} | {fpct(s['chg1m'])} |" if s else f"| {zh} | {t} | {na(t)} | | |")
    L += ["", "## 表6 市场宽度（成分股）", "| 指标 | 标普500 | 纳指100 |", "|---|---|---|"]
    b1, b2 = market["breadth"].get("sp500") or {}, market["breadth"].get("ndx") or {}
    for key, zh in (("adv", "上涨家数"), ("dec", "下跌家数"), ("new_highs", "52周新高"), ("new_lows", "52周新低")):
        L.append(f"| {zh} | {b1.get(key, '—')} | {b2.get(key, '—')} |")
    for n in (20, 50, 100, 200):
        L.append(f"| 高于{n}日线 | {fpct(b1.get(f'above_ma{n}'), 0).lstrip('+')} | {fpct(b2.get(f'above_ma{n}'), 0).lstrip('+')} |")
    L += ["", "## 表7 技术面", "| 标的 | 收盘 | 20日线 | 50日线 | 100日线 | 200日线 | RSI | MACD | 20日高/低 |", "|---|---|---|---|---|---|---|---|---|"]
    for t in cfg["technicals"]:
        s = st.get(t)
        if not s:
            L.append(f"| {t} | {na(t)} ||||||||")
            continue
        macd = "—" if s.get("macd") is None else ("多头" if s["macd"] > s["macd_signal"] else "空头")
        L.append(f"| {t} | {fp(s['close'])} | {fp(s['ma20'])} | {fp(s['ma50'])} | {fp(s['ma100'])} | {fp(s['ma200'])} | "
                 f"{fp(s['rsi14'], 0)} | {macd} | {fp(s['hi20'])}/{fp(s['lo20'])} |")
    L += ["", "## 表8 涨跌幅榜（标普500 + 纳指100，股价 > $5）"]
    for title, key in (("涨幅前 10", "gainers"), ("跌幅前 10", "losers")):
        L += [f"**{title}**", "| 代码 | 公司 | 收盘 | 1日 | 量比 |", "|---|---|---|---|---|"]
        for t in market["movers"][key]:
            s = st[t]
            L.append(f"| {t} | {names.get(t, '')} | {fp(s['close'])} | {fpct(s['chg1d'])} | {fp(s['vol_ratio'])} |")
    L += ["", "## 表9 重点股票", "| 分组 | 代码 | 收盘 | 1日 | 5日 | 相对20日线 | 距52周高 | RSI | 备注 |", "|---|---|---|---|---|---|---|---|---|"]
    for grp, ts in list(cfg["groups"].items()) + list(cfg["portfolio"].items()):
        for t in ts:
            s = st.get(t)
            if not s:
                L.append(f"| {grp} | {t} | {na(t)} |||||||")
                continue
            tag = "52周新高" if s["new_high"] else ("52周新低" if s["new_low"] else "")
            L.append(f"| {grp} | {t} | {fp(s['close'])} | {fpct(s['chg1d'])} | {fpct(s['chg5d'])} | {fpos(s['vs_ma20'])} | "
                     f"{fpct(pct(s['close'], s['hi52']), 1)} | {fp(s['rsi14'], 0)} | {tag} |")
    return "\n".join(L) + "\n"


def main(now_ny=None):
    now_ny = now_ny or dt.datetime.now(NY)
    ft = final_through(now_ny).isoformat()
    cfg = json.load(open("brief_config.json", encoding="utf-8")) if os.path.exists("brief_config.json") else None
    refresh_universe(now_ny.date())
    sp500, ndx = read_names("sp500.csv"), read_names("ndx.csv")
    names = {**ndx, **sp500}
    universe = list(dict.fromkeys(list(sp500) + list(ndx) + read_list("universe.txt")))
    extra = []
    if cfg:
        for v in list(cfg["groups"].values()) + list(cfg["portfolio"].values()) + list(cfg["themes"].values()):
            extra += v
        aliases = set(cfg.get("macro_symbols", {}).values())
        extra += list(cfg["sectors"].values()) + cfg["technicals"] + [t for t in cfg["indices"] if TICKER_RE.match(t) and t not in aliases]
    tickers = list(dict.fromkeys(CORE + read_list("tickers.txt") + [t for t in extra if TICKER_RE.match(t)] + universe))
    macro = (cfg or {}).get("macro_symbols", {})
    long_, recent = {}, {}
    crypto = [m for m in macro if m.endswith("-USD")]
    for group in (tickers, [m for m in macro if m not in crypto], crypto):   # one time zone per download, else dates shift
        if group:
            long_.update(yahoo(group, "1y"))
            recent.update(yahoo(group, "1mo"))          # Yahoo's 1y series can lag a day behind the 1mo one
    diag = {t: {"1y": (long_.get(t) or [{}])[-1].get("date"), "1mo": (recent.get(t) or [{}])[-1].get("date")}
            for t in ("QQQ", "AAPL", "^GSPC", "^TNX")}
    print("last bar by download:", diag)
    raw = {t: merge_rows(long_.get(t), recent.get(t)) for t in set(long_) | set(recent)}
    data = {t: rows for t, rows in raw.items() if t in tickers}
    try:
        prev = json.load(open("latest.json", encoding="utf-8")).get("tickers", {})
    except Exception:
        prev = {}
    kept = 0
    for t, rows in prev.items():                        # never lose a confirmed bar the previous run had
        if t in data and rows and rows[-1]["date"] > data[t][-1]["date"]:
            kept += 1
        if t in data:
            data[t] = merge_rows(rows, data[t])
    if kept:
        print(f"kept newer bars from the previous latest.json for {kept} tickers")
    sources = {t: "yahoo" for t in data}
    for t in read_list("tickers.txt") + CORE:          # fallback for the names we really need
        if t not in data or data[t][-1]["date"] < ft:
            rows = stooq(t)
            if rows and (t not in data or rows[-1]["date"] > data[t][-1]["date"]):
                data[t], sources[t] = rows, "stooq (adj = close)"
    gen = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    final = {t: [r for r in rows if r["date"] <= ft] for t, rows in data.items()}
    tick = {t: [{k: r[k] for k in ("date", "open", "high", "low", "close", "adj")} for r in rows[-KEEP:]]
            for t, rows in final.items() if rows}
    missing = sorted(t for t in tickers if t not in tick)
    stale_core = [t for t in CORE if t not in tick or tick[t][-1]["date"] != ft]
    with open("latest.json", "w", encoding="utf-8") as f:
        json.dump({"generated_at": gen, "final_through": ft, "tickers": tick, "sources": {t: sources.get(t) for t in tick},
                   "missing": missing, "stale_core": stale_core}, f, separators=(",", ":"))
    print(f"final_through {ft}; {len(tick)} tickers; missing {len(missing)}; stale core {stale_core}")
    if not cfg:
        return
    # ---- market data for the brief ----
    st = {t: stats(rows) for t, rows in final.items() if rows}
    for sym, alias in macro.items():                    # macro series: bars up to the end of final_through
        rows = [r for r in raw.get(sym, []) if r["date"] <= ft]
        if rows:
            st[alias] = stats(rows)
    movers = [t for t in set(sp500) | set(ndx) if st.get(t) and st[t]["date"] == ft and st[t]["close"] > 5 and st[t]["chg1d"] is not None]
    movers.sort(key=lambda t: st[t]["chg1d"])
    keep = set(extra) | set(macro.values()) | set(movers[:10]) | set(movers[-10:]) | set(read_list("tickers.txt"))
    market = {"generated_at": gen, "final_through": ft,
              "assets": {t: rnd(st[t]) for t in sorted(keep) if st.get(t)},
              "breadth": {"sp500": breadth(sp500, st, ft), "ndx": breadth(ndx, st, ft)},
              "movers": {"gainers": list(reversed(movers[-10:])), "losers": movers[:10]},
              "names": {t: names.get(t, "") for t in sorted(keep) if names.get(t)}}
    with open("market.json", "w", encoding="utf-8") as f:
        json.dump(market, f, ensure_ascii=False, separators=(",", ":"))
    text = render(market, cfg, names)
    os.makedirs("tables", exist_ok=True)
    for path in ("brief_tables.md", os.path.join("tables", ft + ".md")):
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    print(f"market.json: {len(market['assets'])} assets; breadth sp500 {market['breadth']['sp500'] and market['breadth']['sp500']['n']}")


if __name__ == "__main__":
    main()
