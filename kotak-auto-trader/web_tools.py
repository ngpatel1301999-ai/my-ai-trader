"""Free web research for the AI: search + read pages + NSE news. Stdlib only.
Used by 'research X deeply'. Fails gracefully (returns '' / [] if blocked).
"""
import html
import logging
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

log = logging.getLogger("web")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

# Short blurbs so research NEVER confuses TITAN-the-stock with a submarine.
COMPANY = {
    "RELIANCE": "Reliance Industries — oil, retail, Jio. NSE: RELIANCE.",
    "INFY": "Infosys — IT services. NSE: INFY.",
    "TCS": "Tata Consultancy Services — IT services. NSE: TCS.",
    "HDFCBANK": "HDFC Bank — private bank. NSE: HDFCBANK.",
    "TMPV": "Tata Motors Passenger Vehicles (ex-TATAMOTORS pax). NSE: TMPV.",
    "TMCV": "Tata Motors Commercial Vehicles. NSE: TMCV.",
    "SBIN": "State Bank of India. NSE: SBIN.",
    "ICICIBANK": "ICICI Bank — private bank. NSE: ICICIBANK.",
    "LT": "Larsen & Toubro — engineering & infra. NSE: LT.",
    "AXISBANK": "Axis Bank. NSE: AXISBANK.",
    "KOTAKBANK": "Kotak Mahindra Bank. NSE: KOTAKBANK.",
    "ITC": "ITC — FMCG, hotels, paper. NSE: ITC.",
    "HINDUNILVR": "Hindustan Unilever — FMCG. NSE: HINDUNILVR.",
    "BHARTIARTL": "Bharti Airtel — telecom. NSE: BHARTIARTL.",
    "MARUTI": "Maruti Suzuki — passenger cars. NSE: MARUTI.",
    "TITAN": "Titan Company Ltd — Tanishq jewellery, watches, eyewear. NSE: TITAN. NOT the submarine.",
    "SUNPHARMA": "Sun Pharma. NSE: SUNPHARMA.",
    "NTPC": "NTPC — power. NSE: NTPC.",
    "ONGC": "ONGC — oil & gas. NSE: ONGC.",
}

ALIASES = {
    "ril": "RELIANCE", "reliance": "RELIANCE",
    "infosys": "INFY", "infy": "INFY",
    "tcs": "TCS",
    "hdfc": "HDFCBANK", "hdfcbank": "HDFCBANK", "hdfc bank": "HDFCBANK",
    "tata motors": "TMPV", "tatamotors": "TMPV", "tmpv": "TMPV", "tmcv": "TMCV",
    "sbi": "SBIN", "sbin": "SBIN",
    "icici": "ICICIBANK", "icicibank": "ICICIBANK",
    "l&t": "LT", "larsen": "LT",
    "itc": "ITC",
    "hul": "HINDUNILVR", "unilever": "HINDUNILVR",
    "airtel": "BHARTIARTL", "bharti": "BHARTIARTL", "bharti airtel": "BHARTIARTL",
    "maruti": "MARUTI",
    "titan": "TITAN", "tanishq": "TITAN",
    "sunpharma": "SUNPHARMA", "ntpc": "NTPC", "ongc": "ONGC",
    "kotak": "KOTAKBANK", "axis": "AXISBANK",
    "nifty": "NIFTY", "nifty50": "NIFTY", "nifty 50": "NIFTY",
    "sensex": "SENSEX", "banknifty": "BANKNIFTY", "bank nifty": "BANKNIFTY",
    "tatapower": "TATAPOWER", "tata power": "TATAPOWER",
    "rpower": "RPOWER", "reliance power": "RPOWER",
    "idea": "IDEA", "vodafone": "IDEA", "vodafone idea": "IDEA",
}

INDEX = {"NIFTY": "^NSEI", "NIFTY50": "^NSEI", "SENSEX": "^BSESN",
         "BANKNIFTY": "^NSEBANK"}
_SKIP_TICKER = {"NSE", "BSE", "EQ", "BUY", "SELL", "THE", "AND", "FOR", "ANY",
                "NEWS", "LAST", "DAYS", "GOOD", "SWING", "SCAN", "FIND", "ABOUT",
                "WITH", "FROM", "THIS", "THAT", "HAVE", "WANT", "JUST",
                "COMMODITY", "COMMODITIES", "MCX", "COMEX", "CRYPTO",
                "GOOGLE", "REDMI", "PIXEL", "ANDROID", "PHONE", "PHONES",
                "LAUNCH", "EVENT", "EVENTS", "TODAY", "MARKET", "MARKETS",
                "INDIAN", "STOCK", "STOCKS", "HIGHLIGHT", "HIGHLIGHTS",
                "TELL", "WHAT", "WHO", "WHY", "HOW", "LATEST", "UPDATE"}


def _unwrap_ddg(u: str) -> str:
    try:
        if "uddg=" in u:
            q = urllib.parse.parse_qs(urllib.parse.urlsplit(u).query)
            if q.get("uddg"):
                return urllib.parse.unquote(q["uddg"][0])
    except Exception:
        pass
    return u


def web_search(query: str, n: int = 5) -> list:
    """DuckDuckGo lite search. Returns [{title, url, snip}]."""
    out = []
    try:
        url = "https://lite.duckduckgo.com/lite/?q=" + urllib.parse.quote(query)
        req = urllib.request.Request(url, headers=UA)
        raw = urllib.request.urlopen(req, timeout=12).read().decode("utf-8", "ignore")
        anchors = re.findall(r"<a[^>]*class='result-link'[^>]*>([^<]*)</a>", raw)
        hrefs = re.findall(r"<a[^>]*href=\"([^\"]+)\"[^>]*class='result-link'", raw)
        snips = re.findall(r"result-snippet'>(.*?)</td>", raw, re.S)
        for i in range(min(n, len(anchors), len(hrefs))):
            s = re.sub(r"<[^>]+>", " ", snips[i] if i < len(snips) else "")
            out.append({"title": html.unescape(anchors[i]).strip()[:120],
                        "url": _unwrap_ddg(html.unescape(hrefs[i]))[:300],
                        "snip": html.unescape(s).strip()[:250]})
    except Exception as e:
        log.warning("web_search failed: %s", e)
    return out


def web_read(url: str, max_chars: int = 4000) -> str:
    """Fetch a page, return plain text."""
    try:
        if url.startswith("//"):
            url = "https:" + url
        req = urllib.request.Request(url, headers=UA)
        raw = urllib.request.urlopen(req, timeout=15).read()[:2_000_000].decode("utf-8", "ignore")
        raw = re.sub(r"(?is)<(script|style|nav|footer|header)[^>]*>.*?</\1>", " ", raw)
        txt = re.sub(r"<[^>]+>", " ", raw)
        txt = html.unescape(re.sub(r"\s+", " ", txt)).strip()
        return txt[:max_chars]
    except Exception as e:
        log.warning("web_read failed: %s", e)
        return ""


def yahoo_chart(symbol: str, range="5d", interval="1d"):
    """Yahoo chart. Tries NSE (.NS) then BSE (.BO). Index tickers start with ^."""
    import json as _j
    symbol = (symbol or "").strip()
    if (symbol.startswith("^") or "=" in symbol or "-" in symbol
            or symbol.endswith("=F")):
        tickers = [symbol]
    else:
        symbol = symbol.upper()
        tickers = [symbol + ".NS", symbol + ".BO"]
    last_err = None
    for t in tickers:
        try:
            url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{t}"
                   f"?interval={interval}&range={range}")
            req = urllib.request.Request(url, headers=UA)
            d = _j.loads(urllib.request.urlopen(req, timeout=12).read().decode())
            res = d["chart"]["result"][0]
            return t, res
        except Exception as e:
            last_err = e
    log.warning("yahoo chart failed for %s: %s", symbol, last_err)
    return None, None


def yahoo_prev_close(nse_symbol: str):
    """Independent price. Returns (prev_close, last_price) or (None, None)."""
    t, res = yahoo_chart(nse_symbol, range="5d", interval="1d")
    if not res:
        return None, None
    meta = res.get("meta") or {}
    return meta.get("chartPreviousClose"), meta.get("regularMarketPrice")


def yahoo_daily(symbol: str, days: int = 90) -> list:
    """Daily candles oldest->newest: [{'ts','o','h','l','c','v'}]. NSE then BSE."""
    rng = "6mo" if days > 80 else "3mo"
    t, res = yahoo_chart(symbol, range=rng, interval="1d")
    if not res:
        return []
    ts = res.get("timestamp") or []
    q = ((res.get("indicators") or {}).get("quote") or [{}])[0]
    out = []
    for i, stamp in enumerate(ts):
        try:
            o, h, l, c = q["open"][i], q["high"][i], q["low"][i], q["close"][i]
            v = (q.get("volume") or [0])[i] or 0
            if None in (o, h, l, c):
                continue
            out.append({"ts": stamp, "o": float(o), "h": float(h),
                        "l": float(l), "c": float(c), "v": float(v)})
        except (TypeError, ValueError, IndexError, KeyError):
            pass
    return out


def google_news(query: str, n: int = 5) -> list:
    """Google News RSS (India). Returns [{title, url, snip}]."""
    out = []
    try:
        url = ("https://news.google.com/rss/search?q="
               + urllib.parse.quote(query) + "&hl=en-IN&gl=IN&ceid=IN:en")
        req = urllib.request.Request(url, headers=UA)
        raw = urllib.request.urlopen(req, timeout=12).read()
        root = ET.fromstring(raw)
        for item in root.findall(".//item")[:n]:
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            src = ""
            src_el = item.find("source")
            if src_el is not None:
                src = (src_el.text or "").strip()
            if title:
                out.append({"title": title[:140], "url": link[:300],
                            "snip": src})
    except Exception as e:
        log.warning("google_news failed: %s", e)
    return out


def extract_nse_symbol(text: str) -> str:
    """Pull an NSE ticker out of casual English. TITAN != submarine."""
    t = (text or "").lower()
    # longer aliases first
    for alias, sym in sorted(ALIASES.items(), key=lambda kv: -len(kv[0])):
        if re.search(r"(?<![a-z])" + re.escape(alias) + r"(?![a-z])", t):
            return sym
    for sym in COMPANY:
        if re.search(r"(?<![a-z])" + sym.lower() + r"(?![a-z])", t):
            return sym
    for m in re.finditer(r"\b([A-Z]{2,12}(?:-[A-Z]{2,12})?)\b", text or ""):
        if m.group(1) not in _SKIP_TICKER:
            return m.group(1)
    return ""


def nse_research(symbol: str) -> dict:
    """Facts pack for one NSE stock: Yahoo price + story text (no links)."""
    symbol = (symbol or "").upper().replace("-EQ", "")
    name = COMPANY.get(symbol, symbol + " NSE India stock")
    prev, last = yahoo_prev_close(symbol)
    q = f"{symbol} NSE stock {name.split('—')[0].strip()}"
    news = []
    try:
        import moneycontrol
        news = moneycontrol.news(f"{symbol} {name.split('—')[0].strip()} NSE", 5) or []
    except Exception as e:
        log.warning("moneycontrol news: %s", e)
    if len(news) < 3:
        news = (news or []) + news_digest(q, 5)
    clean = []
    seen = set()
    for h in news:
        title = strip_urls(h.get("title") or "")
        key = title.lower()[:80]
        if not title or key in seen:
            continue
        seen.add(key)
        body = strip_urls(h.get("body") or "")
        clean.append({"title": title, "body": body, "snip": "", "url": ""})
        if len(clean) >= 6:
            break
    return {"symbol": symbol, "name": name, "last": last, "prev": prev, "news": clean}


_URL_RE = re.compile(r"https?://\S+|\bwww\.\S+|\b[\w.-]+\.(com|in|org|net|co)\b", re.I)


def strip_urls(s: str) -> str:
    """Telegram auto-links foo.com — never leave domains in chat text."""
    s = _URL_RE.sub("", s or "")
    s = re.sub(r"\s*[-–—|]\s*(Moneycontrol|Google News|Yahoo).*$", "", s, flags=re.I)
    s = re.sub(r"\s*[-–—|]\s*$", "", s)
    return re.sub(r"\s+", " ", s).strip(" -–—|")


def page_summary(url: str) -> str:
    """Article lead from og:description / meta / first real paragraph."""
    if not url or url.startswith("https://news.google.com"):
        return ""
    try:
        if url.startswith("//"):
            url = "https:" + url
        req = urllib.request.Request(url, headers=UA)
        raw = urllib.request.urlopen(req, timeout=12).read()[:500_000].decode("utf-8", "ignore")
        for pat in (
            r'property=["\']og:description["\'][^>]*content=["\']([^"\']+)',
            r'content=["\']([^"\']+)["\'][^>]*property=["\']og:description["\']',
            r'name=["\']description["\'][^>]*content=["\']([^"\']+)',
            r'content=["\']([^"\']+)["\'][^>]*name=["\']description["\']',
        ):
            m = re.search(pat, raw, re.I)
            if m:
                t = strip_urls(html.unescape(m.group(1)))
                if len(t) > 40:
                    return t[:400]
        raw = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", raw)
        for p in re.findall(r"<p[^>]*>(.*?)</p>", raw, re.I | re.S):
            t = strip_urls(html.unescape(re.sub(r"<[^>]+>", " ", p)))
            if len(t) > 80 and not re.search(
                    r"cookie|subscribe|advertisement|outdated browser|javascript", t, re.I):
                return t[:400]
    except Exception as e:
        log.warning("page_summary: %s", e)
    return ""


def _rss_items(url: str, n: int = 8) -> list:
    """RSS title + description text. No links kept."""
    out = []
    try:
        req = urllib.request.Request(url, headers=UA)
        raw = urllib.request.urlopen(req, timeout=12).read()
        root = ET.fromstring(raw)
        for item in root.findall(".//item")[:n]:
            title = strip_urls(item.findtext("title") or "")
            desc = item.findtext("description") or ""
            desc = strip_urls(html.unescape(re.sub(r"<[^>]+>", " ", desc)))
            if desc.lower() in title.lower() or len(desc) < 40:
                desc = ""
            if title:
                out.append({"title": title[:160], "body": desc[:400],
                            "snip": "", "url": ""})
    except Exception as e:
        log.warning("rss %s: %s", url[:60], e)
    return out


def news_digest(query: str, n: int = 4) -> list:
    """Headlines + what the story actually says. No URLs in the result."""
    q = re.sub(r"\bsite:\S+", "", query or "").strip() or "India markets"
    q = re.sub(r"\s+", " ", q)
    # used by entity filters inside add()
    query = q
    feeds = [
        "https://www.bing.com/news/search?q=" + urllib.parse.quote(q) + "&format=rss",
    ]
    low = q.lower()
    if re.search(r"gold|silver|crude|mcx|commodit|bullion|oil", low):
        feeds.append("https://economictimes.indiatimes.com/markets/commodities/rssfeeds/1808152121.cms")
        if "gold" in low:
            feeds.append("https://feeds.finance.yahoo.com/rss/2.0/headline?s=GC=F&region=US&lang=en-US")
        elif "silver" in low:
            feeds.append("https://feeds.finance.yahoo.com/rss/2.0/headline?s=SI=F&region=US&lang=en-US")
        elif "crude" in low or "oil" in low:
            feeds.append("https://feeds.finance.yahoo.com/rss/2.0/headline?s=CL=F&region=US&lang=en-US")
    keys = [w for w in re.findall(r"[a-z]{3,}", low)
            if w not in ("site", "news", "india", "the", "and", "for", "nse",
                         "bse", "stock", "today", "what", "about")]
    seen, rows = set(), []

    def story_key(title: str) -> str:
        t = re.sub(r"[^a-z0-9 ]+", " ", (title or "").lower())
        drop = {"the", "a", "an", "of", "for", "in", "on", "to", "and", "or",
                "latest", "today", "news", "launch", "launches", "date",
                "confirmed", "expected", "everything", "you", "need", "know",
                "series", "india", "full", "specs", "specifications", "price"}
        words = [w for w in t.split() if w not in drop and len(w) > 2]
        return " ".join(words[:6])

    def add(items, require_key=False):
        for h in items:
            title = strip_urls(h.get("title") or "")
            key = story_key(title) or title.lower()[:50]
            if not title or key in seen:
                continue
            if _FILLER.search(title) or _FILLER.search(h.get("body") or ""):
                continue
            words = set(key.split())
            if any(len(words & set(s.split())) >= 4 for s in seen if s):
                continue
            if "world bank" in q.lower():
                blob = (title + " " + (h.get("body") or "")).lower()
                if "world bank" not in blob:
                    continue
            if "nse ipo" in q.lower() or "nse ipo" in (query or "").lower():
                blob = (title + " " + (h.get("body") or "")).lower()
                if "nse" not in blob or "ipo" not in blob:
                    continue
                if "jindal" in blob and "nse ipo" not in blob:
                    continue
            if require_key and keys:
                blob = (title + " " + (h.get("body") or "")).lower()
                if not any(k in blob for k in keys[:6]):
                    continue
            seen.add(key)
            body = strip_urls(h.get("body") or "")
            if body.lower() in title.lower():
                body = ""
            rows.append({"title": title[:160], "body": body[:400],
                         "snip": "", "url": ""})

    for fu in feeds:
        add(_rss_items(fu, 10), require_key=True)
        if len([r for r in rows if r.get("body")]) >= n:
            break
    if len(rows) < n:
        add(google_news(q, n + 3), require_key=False)
    # prefer rows that have story text
    rows.sort(key=lambda r: (0 if r.get("body") else 1))
    return rows[:n]


def wiki_summary(query: str) -> str:
    """Short Wikipedia extract. No URLs."""
    import json as _j
    q = re.sub(r"\s+", " ", (query or "").strip())
    if len(q) < 2:
        return ""
    try:
        url = ("https://en.wikipedia.org/w/api.php?action=opensearch&search="
               + urllib.parse.quote(q) + "&limit=1&namespace=0&format=json")
        req = urllib.request.Request(url, headers=UA)
        data = _j.loads(urllib.request.urlopen(req, timeout=10).read().decode())
        title = (data[1] or [None])[0]
        if not title:
            return ""
        u2 = ("https://en.wikipedia.org/api/rest_v1/page/summary/"
              + urllib.parse.quote(title))
        req = urllib.request.Request(u2, headers={**UA, "Accept": "application/json"})
        d = _j.loads(urllib.request.urlopen(req, timeout=10).read().decode())
        return strip_urls(d.get("extract") or "")[:900]
    except Exception as e:
        log.warning("wiki: %s", e)
        return ""


_FILLER = re.compile(
    r"afternoon bulletin|top 10\s*\|+|stay on top of the most important|"
    r"top news of the day september|bring you the top|"
    r"provides the latest business news|personal finance news from the world of business|"
    r"check details here|stay updated for accurate|"
    r"what is the weather forecast for today",
    re.I)

# Keep these as one thing. "world bank" ≠ "world's top banks".
_ENTITIES = (
    ("world bank", '"World Bank" (institution OR IMF OR development) -"top 10 banks" -"top performing banks"'),
    ("nse ipo", "NSE IPO listing BSE"),
    ("grey market", "NSE IPO GMP"),
    ("zydus", "Zydus Healthcare Zydus Cadila Zydus Lifesciences India"),
)


def normalize_query(text: str) -> str:
    """Fix common typos so 'wether' is weather, not news."""
    t = text or ""
    t = re.sub(r"\b(wether|wheather|weater|wather)\b", "weather", t, flags=re.I)
    t = re.sub(r"\bforcast\b", "forecast", t, flags=re.I)
    t = re.sub(r"\btemprature\b", "temperature", t, flags=re.I)
    t = re.sub(r"\b(ahemdabad|ahmdabad)\b", "Ahmedabad", t, flags=re.I)
    t = re.sub(r"\bgujrat\b", "Gujarat", t, flags=re.I)
    return t


def query_intent(text: str) -> str:
    t = normalize_query(text).lower()
    if re.search(r"\b(weather|forecast|rain|rainfall|temperature|imd|"
                 r"thunder|humid|heatwave|red alert)\b", t):
        return "weather"
    if re.search(r"\b(headline|headlines|top news|india news|news of india|"
                 r"today'?s news|news headlines)\b", t) and re.search(
                     r"\b(india|indian|bharat)\b", t):
        return "india_news"
    if re.search(r"\b(headline|headlines|top news|latest news)\b", t):
        return "news"
    if re.match(r"\s*(is|are|does|do|can|will|was|were)\b", t) or (
            "?" in t and re.search(r"\b(is|are|does|do)\b", t)):
        return "yesno"
    if re.search(r"\b(who is|what is|what are|explain|meaning of)\b", t):
        return "explain"
    return "facts"


def search_query(text: str) -> str:
    """Search string that matches the question, not leftover filler words."""
    t = text or ""
    low = t.lower()
    for needle, repl in _ENTITIES:
        if needle in low:
            return repl
    intent = query_intent(t)
    if intent == "india_news":
        return "India news today"
    q = re.sub(r"\blanch\b", "launch", t, flags=re.I)
    q = re.sub(
        r"\b(please tell me|tell me about|tell me|please|kindly|can you|"
        r"what are|what is|what's|whats|who is|is currently|"
        r"latest top news about|latest top news|top news headlines of|"
        r"top news headlines|top news about|news headlines of|"
        r"news headlines|headlines of|latest|today|update|updates|"
        r"headline|headlines|about)\b",
        " ", q, flags=re.I)
    q = re.sub(r"\s+", " ", q).strip(" ?!.,")
    return q or t


def _wiki_related(title: str, extract: str, query: str) -> bool:
    blob = ((title or "") + " " + (extract or "")[:280]).lower()
    if not blob.strip():
        return False
    qw = set(re.findall(r"[a-z]{3,}", (query or "").lower()))
    drop = {"the", "and", "for", "are", "was", "does", "did", "can", "will",
            "what", "who", "why", "how", "latest", "today", "news", "about",
            "tell", "please", "top", "from", "with", "this", "that", "listing",
            "exchange", "currently"}
    qw -= drop
    # NSE → national stock exchange
    if "nse" in (query or "").lower():
        qw.update({"national", "stock", "exchange"})
    if "world bank" in (query or "").lower():
        return "world bank" in blob and "song" not in blob and "brandy" not in blob
    ww = set(re.findall(r"[a-z]{3,}", blob))
    return len(qw & ww) >= 2


def wiki_lookup(query: str):
    """(title, extract) or ('', '')."""
    import json as _j
    q = re.sub(r"\s+", " ", (query or "").strip())
    if len(q) < 2:
        return "", ""
    try:
        url = ("https://en.wikipedia.org/w/api.php?action=opensearch&search="
               + urllib.parse.quote(q) + "&limit=1&namespace=0&format=json")
        req = urllib.request.Request(url, headers=UA)
        data = _j.loads(urllib.request.urlopen(req, timeout=10).read().decode())
        title = (data[1] or [None])[0] or ""
        if not title:
            return "", ""
        u2 = ("https://en.wikipedia.org/api/rest_v1/page/summary/"
              + urllib.parse.quote(title))
        req = urllib.request.Request(u2, headers={**UA, "Accept": "application/json"})
        d = _j.loads(urllib.request.urlopen(req, timeout=10).read().decode())
        return title, strip_urls(d.get("extract") or "")[:900]
    except Exception as e:
        log.warning("wiki: %s", e)
        return "", ""


def india_top_news(n: int = 6) -> list:
    rows = _rss_items(
        "https://news.google.com/rss?hl=en-IN&gl=IN&ceid=IN:en", n + 4)
    out = []
    for h in rows:
        title = h.get("title") or ""
        if _FILLER.search(title):
            continue
        out.append(h)
        if len(out) >= n:
            break
    return out


def general_facts(query: str) -> dict:
    """Facts pack shaped to the question. Wiki only if it is the same topic."""
    intent = query_intent(query)
    q = search_query(query)
    if intent == "weather":
        return weather_facts(query)
    if intent == "india_news":
        news = india_top_news(6) or news_digest(q, 6)
        wiki = ""
    else:
        news = news_digest(q, 5)
        wiki = ""
        if intent in ("explain", "facts", "yesno"):
            title, extract = wiki_lookup(q)
            if extract and _wiki_related(title, extract, query):
                wiki = extract
    clean = []
    for h in news:
        title = strip_urls(h.get("title") or "")
        if not title or _FILLER.search(title):
            continue
        body = strip_urls(h.get("body") or "")
        if _FILLER.search(body) or re.search(r"provides the latest business news", body, re.I):
            body = ""
        clean.append({"title": title, "body": body, "snip": "", "url": ""})
    return {"query": query, "intent": intent, "search": q,
            "wiki": wiki, "news": clean[:6]}


_WMO = {
    0: "Clear", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Rime fog", 51: "Light drizzle", 53: "Drizzle",
    55: "Heavy drizzle", 61: "Light rain", 63: "Rain", 65: "Heavy rain",
    71: "Light snow", 73: "Snow", 75: "Heavy snow",
    80: "Rain showers", 81: "Showers", 82: "Heavy showers",
    95: "Thunderstorm", 96: "Thunder + hail", 99: "Severe thunder",
}


def _weather_place(text: str) -> str:
    t = (text or "").lower()
    t = t.replace("gujrat", "gujarat")
    for name in ("ahmedabad", "surat", "vadodara", "rajkot", "mumbai",
                 "delhi", "bengaluru", "bangalore", "pune", "hyderabad",
                 "chennai", "kolkata", "jaipur", "lucknow", "indore"):
        if name in t:
            return name.title() if name != "bangalore" else "Bengaluru"
    if "gujarat" in t:
        return "Ahmedabad"
    return "Ahmedabad"


def weather_facts(query: str) -> dict:
    """Live forecast (Open-Meteo). Not news headlines. No API key."""
    import json as _j
    from datetime import date
    qn = normalize_query(query)
    low = qn.lower()
    place = _weather_place(qn)
    span, days = "week", 5
    if re.search(r"\b(month|monthly|this month)\b", low):
        span, days = "month", 16
    elif re.search(r"next\s+(\d+)\s*day", low):
        span, days = "week", max(1, min(16, int(re.search(r"next\s+(\d+)\s*day", low).group(1))))
    elif re.search(r"\b(today|tonight|now)\b", low) and not re.search(r"\b(next|week|month|days)\b", low):
        span, days = "today", 2
    out = {"query": query, "intent": "weather", "place": place, "span": span,
           "days": days, "news": [], "wiki": "", "daily": [], "now": {}}
    try:
        gurl = ("https://geocoding-api.open-meteo.com/v1/search?name="
                + urllib.parse.quote(place) + "&count=1&language=en")
        req = urllib.request.Request(gurl, headers=UA)
        geo = _j.loads(urllib.request.urlopen(req, timeout=10).read().decode())
        hit = (geo.get("results") or [None])[0]
        if not hit:
            return out
        lat, lon = hit["latitude"], hit["longitude"]
        label = hit.get("name") or place
        admin = hit.get("admin1") or ""
        furl = (
            "https://api.open-meteo.com/v1/forecast?"
            f"latitude={lat}&longitude={lon}"
            "&current=temperature_2m,relative_humidity_2m,weather_code,"
            "precipitation,wind_speed_10m"
            "&daily=weather_code,temperature_2m_max,temperature_2m_min,"
            "precipitation_sum,precipitation_probability_max"
            f"&forecast_days={days}&timezone=Asia%2FKolkata"
        )
        req = urllib.request.Request(furl, headers=UA)
        d = _j.loads(urllib.request.urlopen(req, timeout=12).read().decode())
        cur = d.get("current") or {}
        out["now"] = {
            "temp": cur.get("temperature_2m"),
            "rh": cur.get("relative_humidity_2m"),
            "wind": cur.get("wind_speed_10m"),
            "code": cur.get("weather_code"),
            "place": f"{label}" + (f", {admin}" if admin else ""),
        }
        daily = d.get("daily") or {}
        dates = list(daily.get("time") or [])
        if span == "month":
            today = date.today()
            keep = []
            for i, day in enumerate(dates):
                try:
                    dd = date.fromisoformat(str(day)[:10])
                    if dd.month == today.month and dd.year == today.year:
                        keep.append(i)
                except Exception:
                    keep.append(i)
            if keep:
                def col(name):
                    arr = daily.get(name) or []
                    return [arr[i] if i < len(arr) else None for i in keep]
                dates = [dates[i] for i in keep]
                daily = {
                    "temperature_2m_max": col("temperature_2m_max"),
                    "temperature_2m_min": col("temperature_2m_min"),
                    "precipitation_sum": col("precipitation_sum"),
                    "precipitation_probability_max": col("precipitation_probability_max"),
                    "weather_code": col("weather_code"),
                }
        for i, day in enumerate(dates):
            out["daily"].append({
                "date": day,
                "tmax": (daily.get("temperature_2m_max") or [None])[i] if i < len(daily.get("temperature_2m_max") or []) else None,
                "tmin": (daily.get("temperature_2m_min") or [None])[i] if i < len(daily.get("temperature_2m_min") or []) else None,
                "rain": (daily.get("precipitation_sum") or [None])[i] if i < len(daily.get("precipitation_sum") or []) else None,
                "pop": (daily.get("precipitation_probability_max") or [None])[i] if i < len(daily.get("precipitation_probability_max") or []) else None,
                "code": (daily.get("weather_code") or [None])[i] if i < len(daily.get("weather_code") or []) else None,
            })
    except Exception as e:
        log.warning("weather: %s", e)
    return out


def market_facts() -> dict:
    """Nifty + Sensex last + today's market story text."""
    n_prev, n_last = yahoo_prev_close("^NSEI")
    s_prev, s_last = yahoo_prev_close("^BSESN")
    news = news_digest("Indian stock market today Nifty Sensex", 6)
    return {"nifty_prev": n_prev, "nifty": n_last,
            "sensex_prev": s_prev, "sensex": s_last, "news": news}
