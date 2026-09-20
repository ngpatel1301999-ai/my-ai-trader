"""NSE equity directory + scan filters.
Trade watchlist (.env) stays SMALL. Scan can be Nifty 50 / 200 / name filter.
Full listed-equity refresh runs on YOUR laptop (NSE often blocks datacenters).
BSE: research/quote via Yahoo .BO; live orders stay NSE (Kotak nse_cm).
"""
import csv
import io
import json
import logging
import os
import re
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

log = logging.getLogger("universe")

CACHE = "nse_equity.json"
SCAN_CAP = 40  # never hammer APIs with 2000 names in one Telegram reply

# Nifty 50 as of Sep 2026 (TMPV replaced TATAMOTORS after the demerger).
NIFTY50 = [
    "ADANIENT", "ADANIPORTS", "APOLLOHOSP", "ASIANPAINT", "AXISBANK",
    "BAJAJ-AUTO", "BAJFINANCE", "BAJAJFINSV", "BEL", "BHARTIARTL",
    "CIPLA", "COALINDIA", "DRREDDY", "EICHERMOT", "ETERNAL",
    "GRASIM", "HCLTECH", "HDFCBANK", "HDFCLIFE", "HINDALCO",
    "HINDUNILVR", "ICICIBANK", "ITC", "INFY", "INDIGO",
    "JSWSTEEL", "JIOFIN", "KOTAKBANK", "LT", "M&M",
    "MARUTI", "MAXHEALTH", "NTPC", "NESTLEIND", "ONGC",
    "POWERGRID", "RELIANCE", "SBILIFE", "SHRIRAMFIN", "SBIN",
    "SUNPHARMA", "TCS", "TATACONSUM", "TMPV", "TATASTEEL",
    "TECHM", "TITAN", "TRENT", "ULTRACEMCO", "WIPRO",
]

# Liquid extras so 'find bank' / 'scan pharma' work before a full NSE refresh.
NIFTY200_EXTRA = [
    "ABB", "ADANIGREEN", "ADANIPOWER", "ALKEM", "AMBUJACEM", "ASHOKLEY",
    "ASTRAL", "AUBANK", "AUROPHARMA", "BANDHANBNK", "BANKBARODA",
    "BERGEPAINT", "BHARATFORG", "BHEL", "BIOCON", "BOSCHLTD", "BPCL",
    "BRITANNIA", "BSE", "CANBK", "CDSL", "CHOLAFIN", "COFORGE", "COLPAL",
    "CONCOR", "CUMMINSIND", "DABUR", "DALBHARAT", "DELHIVERY", "DIVISLAB",
    "DLF", "DMART", "EXIDEIND", "FEDERALBNK", "GAIL", "GLENMARK",
    "GODREJCP", "GODREJPROP", "HAL", "HAVELLS", "HEROMOTOCO", "HINDZINC",
    "HUDCO", "ICICIGI", "ICICIPRULI", "IDFCFIRSTB", "IGL", "INDHOTEL",
    "INDUSTOWER", "INDUSINDBK", "IOC", "IRCTC", "IREDA", "IRFC",
    "JINDALSTEL", "JSWENERGY", "KEI", "LAURUSLABS", "LICI", "LODHA",
    "LTIM", "LUPIN", "MANKIND", "MCX", "MOTHERSON", "MPHASIS", "MRF",
    "MUTHOOTFIN", "NAUKRI", "NHPC", "NMDC", "OBEROIRLTY", "OFSS",
    "PAGEIND", "PAYTM", "PEL", "PERSISTENT", "PETRONET", "PFC",
    "PIDILITIND", "PIIND", "PNB", "POLYCAB", "POLICYBZR", "PRESTIGE",
    "PVRINOX", "RECLTD", "SAIL", "SHREECEM", "SIEMENS", "SOLARINDS",
    "SRF", "SUPREMEIND", "SUZLON", "TATACHEM", "TATAPOWER", "TATATECH",
    "TIINDIA", "TORNTPHARM", "TORNTPOWER", "TVSMOTOR", "UNIONBANK",
    "UNITDSPR", "UPL", "VBL", "VEDL", "VOLTAS", "YESBANK", "ZYDUSLIFE",
    "CAMS", "NYKAA", "SWIGGY", "TMCV", "IDEA", "HFCL", "NATIONALUM",
    "RPOWER",
]

SECTOR_HINTS = {
    "bank": "SBIN HDFCBANK ICICIBANK AXISBANK KOTAKBANK FEDERALBNK CANBK UNIONBANK IDFCFIRSTB AUBANK BANDHANBNK INDUSINDBK BANKBARODA PNB",
    "it": "TCS INFY WIPRO HCLTECH TECHM LTIM MPHASIS PERSISTENT COFORGE OFSS NAUKRI",
    "pharma": "SUNPHARMA CIPLA DRREDDY DIVISLAB LUPIN ALKEM AUROPHARMA BIOCON GLENMARK TORNTPHARM ZYDUSLIFE MANKIND LAURUSLABS",
    "auto": "MARUTI M&M TMPV TMCV BAJAJ-AUTO EICHERMOT HEROMOTOCO TVSMOTOR ASHOKLEY BHARATFORG MOTHERSON EXIDEIND",
    "metal": "TATASTEEL JSWSTEEL HINDALCO VEDL JINDALSTEL HINDZINC NMDC SAIL NATIONALUM COALINDIA",
    "energy": "RELIANCE ONGC NTPC POWERGRID COALINDIA IOC BPCL GAIL TATAPOWER ADANIGREEN ADANIPOWER NHPC",
    "fmcg": "HINDUNILVR ITC NESTLEIND BRITANNIA DABUR GODREJCP COLPAL TATACONSUM VBL UNITDSPR",
    "jewellery": "TITAN",
    "realty": "DLF LODHA OBEROIRLTY PRESTIGE GODREJPROP",
    "finance": "BAJFINANCE BAJAJFINSV HDFCLIFE SBILIFE SHRIRAMFIN CHOLAFIN MUTHOOTFIN PFC RECLTD JIOFIN LICI ICICIGI",
}


def _seed_rows():
    seen, rows = set(), []
    for s in NIFTY50 + NIFTY200_EXTRA:
        if s not in seen:
            seen.add(s)
            rows.append({"symbol": s, "name": s, "series": "EQ", "index": (
                "nifty50" if s in NIFTY50 else "liquid")})
    return rows


def load() -> list:
    try:
        if os.path.exists(CACHE):
            rows = json.load(open(CACHE)) or []
            if rows:
                return rows
    except Exception as e:
        log.warning("universe cache: %s", e)
    rows = _seed_rows()
    save(rows)
    return rows


def save(rows: list):
    try:
        json.dump(rows, open(CACHE, "w"), indent=0)
    except Exception as e:
        log.warning("universe save: %s", e)


def symbols_in(*groups) -> list:
    rows = load()
    want = set()
    gset = {g.lower() for g in groups}
    if "nifty50" in gset:
        want.update(NIFTY50)
    if "nifty200" in gset or "liquid" in gset:
        want.update(NIFTY50)
        want.update(NIFTY200_EXTRA)
    if not want:
        want.update(r["symbol"] for r in rows)
    return list(want)


def find(query: str, limit: int = 15) -> list:
    """Name/ticker/sector search across the directory."""
    q = (query or "").strip().lower()
    q = re.sub(r"^(find|search|scan)\s+", "", q).strip()
    if not q:
        return []
    # sector shortcut — whole word only ("it" must not match "commodity")
    for sec, blob in SECTOR_HINTS.items():
        if re.search(r"(?<![a-z])" + re.escape(sec) + r"(?![a-z])", q):
            syms = blob.split()
            rows = load()
            by = {r["symbol"]: r for r in rows}
            out = []
            for s in syms:
                r = by.get(s, {"symbol": s, "name": s})
                out.append(r)
            return out[:limit]
    rows = load()
    hits = []
    for r in rows:
        blob = (r.get("symbol", "") + " " + r.get("name", "")).lower()
        if q in blob or r.get("symbol", "").lower() == q:
            hits.append(r)
    if not hits:
        # fuzzy-ish: all tokens
        toks = [t for t in re.split(r"[^a-z0-9]+", q) if len(t) > 2]
        for r in rows:
            blob = (r.get("symbol", "") + " " + r.get("name", "")).lower()
            if any(t in blob for t in toks):
                hits.append(r)
    return hits[:limit]


def resolve_scan(query: str, watchlist: list) -> tuple:
    """Returns (label, [symbols]) capped at SCAN_CAP."""
    q = (query or "").strip().lower()
    q = re.sub(r"^(scan|find|search)\s+", "", q).strip()
    if re.search(r"\bcommodit|\b(mcx|comex)\b|\bcrypto|\b(currency|currencies|forex)\b", q):
        return "not-nse", []
    if not q or q in ("watchlist", "watch", "mine"):
        return "watchlist", watchlist[:SCAN_CAP]
    if any(x in q for x in ("sid", "44ma", "44 ma", "bhanushali", "sniper")):
        return "sid44 nifty100", (NIFTY50 + NIFTY200_EXTRA)[:SCAN_CAP]
    if "nifty50" in q or "nifty 50" in q or q == "n50":
        return "nifty50", NIFTY50[:SCAN_CAP]
    if "nifty100" in q or "nifty 100" in q or q == "n100":
        return "nifty100", (NIFTY50 + NIFTY200_EXTRA)[:SCAN_CAP]
    if "nifty200" in q or "nifty 200" in q or "liquid" in q:
        return "nifty200", (NIFTY50 + NIFTY200_EXTRA)[:SCAN_CAP]
    hits = find(q, limit=SCAN_CAP)
    if hits:
        return f"filter:{q}", [h["symbol"] for h in hits][:SCAN_CAP]
    return "watchlist", watchlist[:SCAN_CAP]


def refresh_from_nse() -> str:
    """Download NSE EQUITY_L.csv (works more often from a home IP than a server)."""
    ua = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
          "Accept": "text/csv,*/*"}
    urls = [
        "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv",
        "https://archives.nseindia.com/content/equities/EQUITY_L.csv",
    ]
    raw = None
    try:
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor())
        opener.addheaders = list(ua.items()) + [("Referer", "https://www.nseindia.com")]
        opener.open("https://www.nseindia.com", timeout=12)
        for u in urls:
            try:
                raw = opener.open(u, timeout=20).read()
                if raw and len(raw) > 1000:
                    break
            except Exception as e:
                log.warning("nse list %s: %s", u, e)
                raw = None
    except Exception as e:
        return f"NSE download failed ({e}). Using built-in Nifty 50/200. Try again from home Wi-Fi."
    if not raw or len(raw) < 1000:
        return "NSE blocked the download (common). Built-in Nifty 50 + 200 liquid names still work. Try `scan nifty50`."
    text = raw.decode("utf-8", "ignore")
    rdr = csv.DictReader(io.StringIO(text))
    rows = []
    for rec in rdr:
        # headers vary slightly
        rec = {k.strip().upper(): (v or "").strip() for k, v in rec.items() if k}
        sym = rec.get("SYMBOL") or rec.get("SM SYMBOL") or ""
        name = rec.get("NAME OF COMPANY") or rec.get("COMPANY NAME") or rec.get("NAME") or sym
        series = rec.get("SERIES") or "EQ"
        if not sym:
            continue
        if series not in ("EQ", "BE", "SM"):
            continue
        rows.append({"symbol": sym.upper(), "name": name, "series": series,
                     "index": "nifty50" if sym.upper() in NIFTY50 else ""})
    if len(rows) < 100:
        return f"Parse looked wrong ({len(rows)} rows). Kept old list."
    save(rows)
    return f"Universe updated: {len(rows)} NSE equities saved. Try `find jewellery` or `scan bank`."


def scan_scores(symbols: list) -> list:
    """Yahoo daily + Sid 44-MA (or classic) score. Parallel, capped."""
    import web_tools
    from swing import score_swing
    try:
        from config import SETTINGS as _S
        style = getattr(_S, "swing_strategy", "sid44")
    except Exception:
        style = "sid44"
    symbols = [s.upper().replace("-EQ", "") for s in symbols if s][:SCAN_CAP]
    out = []

    def one(sym):
        candles = web_tools.yahoo_daily(sym, days=90)
        last = candles[-1]["c"] if candles else None
        if candles:
            score, why, meta = score_swing(candles, style)
        else:
            score, why, meta = 0, ["no data"], {}
        return {"symbol": sym, "score": score, "why": why, "last": last,
                "sl": (meta or {}).get("sl"), "t1": (meta or {}).get("t1"),
                "t2": (meta or {}).get("t2")}

    with ThreadPoolExecutor(max_workers=8) as pool:
        futs = {pool.submit(one, s): s for s in symbols}
        for f in as_completed(futs):
            try:
                out.append(f.result())
            except Exception as e:
                out.append({"symbol": futs[f], "score": 0, "why": [str(e)[:40]],
                            "last": None})
    out.sort(key=lambda r: r["score"], reverse=True)
    return out


def format_scan(label: str, rows: list) -> str:
    if not rows:
        return "Scan empty. Try `scan nifty50` or `find bank`."
    lines = [f"Scan {label} ({len(rows)} names, cap {SCAN_CAP}). Sid 44-MA sniper. Not auto-buy."]
    for r in rows:
        flag = "YES" if r["score"] >= 70 else ("ok" if r["score"] >= 40 else "weak")
        px = f" Rs {r['last']:.1f}" if r.get("last") else ""
        lv = ""
        if r.get("sl") and r.get("t1"):
            lv = f" SL {r['sl']:.0f} T1 {r['t1']:.0f}"
        why = ",".join(r.get("why") or [])[:36]
        lines.append(f"{flag} {r['symbol']}: {r['score']}{px}{lv} ({why})")
    lines.append("Want: (a) research the top name (b) add one to watchlist (c) scan nifty50 ?")
    return "\n".join(lines)
