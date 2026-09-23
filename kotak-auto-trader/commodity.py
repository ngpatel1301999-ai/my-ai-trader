"""PAPER gold / silver / energy / crypto / FX.

Equity + MCX live/history DATA: Kotak Neo (quotes + daily candles).
Currency + crypto live/history: Yahoo (Moneycontrol FX/crypto pages were down).
News: Moneycontrol via public Google News site: filter.

Live MCX / crypto / FX orders are NEVER sent from this module.
Sid 44-MA is NSE equity only — not applied here.
"""
import json
import logging
import os
import re
from datetime import datetime
from zoneinfo import ZoneInfo

import moneycontrol
import paths
import web_tools

IST = ZoneInfo("Asia/Kolkata")

log = logging.getLogger("commodity")
POS_FILE = paths.data_path("commodity_positions.json")

# kind: mcx = try Kotak mcx_fo first; crypto/fx = Yahoo only (not on Neo).
SPECS = {
    "GOLD":   {"yahoo": "GC=F",     "ccy": "USD", "unit": "oz",    "name": "Gold",
               "kind": "mcx", "mcx": "GOLD", "mcx_unit": "10g", "mcx_ccy": "INR"},
    "SILVER": {"yahoo": "SI=F",     "ccy": "USD", "unit": "oz",    "name": "Silver",
               "kind": "mcx", "mcx": "SILVER", "mcx_unit": "kg", "mcx_ccy": "INR"},
    "CRUDE":  {"yahoo": "CL=F",     "ccy": "USD", "unit": "bbl",   "name": "Crude",
               "kind": "mcx", "mcx": "CRUDEOIL", "mcx_unit": "bbl", "mcx_ccy": "INR"},
    "NATGAS": {"yahoo": "NG=F",     "ccy": "USD", "unit": "mmBtu", "name": "Nat Gas",
               "kind": "mcx", "mcx": "NATURALGAS", "mcx_unit": "mmBtu", "mcx_ccy": "INR"},
    "BTC":    {"yahoo": "BTC-USD",  "ccy": "USD", "unit": "BTC",   "name": "Bitcoin",
               "kind": "crypto"},
    "ETH":    {"yahoo": "ETH-USD",  "ccy": "USD", "unit": "ETH",   "name": "Ethereum",
               "kind": "crypto"},
    "USDINR": {"yahoo": "USDINR=X", "ccy": "INR", "unit": "USD",   "name": "USD/INR",
               "kind": "fx"},
    "EURINR": {"yahoo": "EURINR=X", "ccy": "INR", "unit": "EUR",   "name": "EUR/INR",
               "kind": "fx"},
    "GBPINR": {"yahoo": "GBPINR=X", "ccy": "INR", "unit": "GBP",   "name": "GBP/INR",
               "kind": "fx"},
    "JPYINR": {"yahoo": "JPYINR=X", "ccy": "INR", "unit": "JPY",   "name": "JPY/INR",
               "kind": "fx"},
}

MCX_NAMES = tuple(n for n, s in SPECS.items() if s.get("kind") == "mcx")
CRYPTO_NAMES = tuple(n for n, s in SPECS.items() if s.get("kind") == "crypto")
FX_NAMES = tuple(n for n, s in SPECS.items() if s.get("kind") == "fx")

ALIASES = {
    "gold": "GOLD", "silver": "SILVER", "crude": "CRUDE", "oil": "CRUDE",
    "crudeoil": "CRUDE", "natgas": "NATGAS", "nat gas": "NATGAS",
    "natural gas": "NATGAS",
    "btc": "BTC", "bitcoin": "BTC", "eth": "ETH", "ethereum": "ETH",
    "usdinr": "USDINR", "usd/inr": "USDINR", "usd inr": "USDINR",
    "dollar": "USDINR", "eurinr": "EURINR", "euro": "EURINR",
    "gbpinr": "GBPINR", "pound": "GBPINR", "jpyinr": "JPYINR", "yen": "JPYINR",
}


def pick_name(text: str) -> str:
    t = (text or "").lower()
    for alias, name in sorted(ALIASES.items(), key=lambda kv: -len(kv[0])):
        if re.search(r"(?<![a-z])" + re.escape(alias) + r"(?![a-z])", t):
            return name
    u = (text or "").upper().replace("/", "")
    for name in SPECS:
        if re.search(r"(?<![A-Z])" + name + r"(?![A-Z])", u):
            return name
    return ""


def wants_commodity(text: str) -> bool:
    """True if this chat is about commodity / crypto / FX — not NSE Sid."""
    t = (text or "").lower()
    if re.search(r"\bcommodit", t):
        return True
    if re.search(r"\b(mcx|comex)\b", t):
        return True
    if re.search(r"\b(currency|currencies|forex|\bfx\b)\b", t):
        return True
    if re.search(r"\bcrypto", t):
        return True
    return bool(pick_name(text))


def asking_hours(text: str) -> bool:
    t = (text or "").lower()
    if re.search(r"\b(position|portfolio|pnl|task|buy|sell|scan)\b", t):
        return False
    return bool(re.search(
        r"\b(open|closed|close|holiday|hours|session|trading today|"
        r"market (on|off)|is it (open|closed)|currently .{0,40}open)\b", t))


def hours_kind(text: str) -> str:
    t = (text or "").lower()
    if re.search(r"\b(crypto|bitcoin|btc|eth)\b", t):
        return "crypto"
    if re.search(r"\b(gold|silver|crude|natgas|mcx|commodit|comex)\b", t):
        return "mcx"
    if re.search(r"\b(nse|bse|equity|stock|share)\b", t) and not re.search(
            r"\b(currency|forex|fx|usd|inr)\b", t):
        return "equity"
    return "fx"


def hours_report(kind: str = "fx") -> str:
    """Direct yes/no for sessions. Saturday/Sunday: Indian FX/MCX/NSE closed."""
    now = datetime.now(IST)
    wd = now.weekday()  # Mon=0
    hm = now.hour * 60 + now.minute
    stamp = now.strftime("%A %d %b %Y, %H:%M IST")
    nse_eq = wd < 5 and (9 * 60 + 15) <= hm < (15 * 60 + 30)
    nse_fx = wd < 5 and (9 * 60) <= hm < (17 * 60)
    mcx = wd < 5 and (9 * 60) <= hm < (23 * 60 + 30)
    # Spot FX ~24x5: closed Saturday; Sunday from 17:00 IST.
    if wd == 5:
        spot = False
    elif wd == 6:
        spot = hm >= 17 * 60
    else:
        spot = True
    crypto = True

    def yn(ok):
        return "OPEN now" if ok else "CLOSED now"

    if kind == "fx":
        head = "No." if not (nse_fx or spot) else "Yes."
        if wd >= 5 and not spot:
            head = "No."
        return (
            f"{head} Currency trading — {stamp}\n"
            f"• NSE currency futures (USDINR etc.): {yn(nse_fx)}\n"
            f"  Hours: Mon–Fri 9:00 AM – 5:00 PM IST. Weekend = shut.\n"
            f"• Interbank / Yahoo spot FX: {yn(spot)}\n"
            f"  ~Sun 5:00 PM IST → Fri night. Saturday = shut.\n"
            f"Today is {now.strftime('%A')}. "
            f"{'Indian currency market is shut.' if wd >= 5 else ''}\n"
            "PAPER only. /scan_currency shows last Yahoo prints, not a live NSE order."
        ).strip()
    if kind == "mcx":
        head = "Yes." if mcx else "No."
        return (
            f"{head} MCX commodity — {stamp}\n"
            f"• MCX (GOLD/SILVER/CRUDE): {yn(mcx)}\n"
            f"  Hours: Mon–Fri about 9:00 AM – 11:30 PM IST. Weekend = shut.\n"
            "PAPER quotes only. No live MCX order."
        )
    if kind == "crypto":
        return (
            f"Yes. Crypto trades 24/7 — {stamp}\n"
            "PAPER BTC/ETH via Yahoo. No live order."
        )
    head = "Yes." if nse_eq else "No."
    return (
        f"{head} NSE/BSE equity — {stamp}\n"
        f"• Cash equity: {yn(nse_eq)}\n"
        f"  Hours: Mon–Fri 9:15 AM – 3:30 PM IST. Weekend = shut.\n"
        "PAPER until you say live."
    )


class CommodityBook:
    def __init__(self, kotak=None):
        self.kotak = kotak
        self.positions = {}
        self._mcx_cache = {}  # name -> (ts, tok)
        self.load()

    def load(self):
        try:
            if os.path.exists(POS_FILE):
                self.positions = json.load(open(POS_FILE)) or {}
        except Exception as e:
            log.warning("commodity load: %s", e)
            self.positions = {}

    def save(self):
        try:
            json.dump(self.positions, open(POS_FILE, "w"), indent=1)
        except Exception as e:
            log.warning("commodity save: %s", e)

    def _yahoo(self, name: str):
        spec = SPECS.get(name)
        if not spec:
            return None, None, spec
        prev, last = web_tools.yahoo_prev_close(spec["yahoo"])
        return last or prev, prev, spec

    def _kotak_mcx(self, name: str):
        spec = SPECS.get(name) or {}
        mcx = spec.get("mcx")
        if not mcx or not self.kotak:
            return None, None, None
        try:
            hit = self._mcx_cache.get(name)
            ts = tok = None
            if hit:
                ts, tok = hit
            else:
                ts, tok = self.kotak.search_token(mcx, "mcx_fo")
                if tok:
                    self._mcx_cache[name] = (ts, tok)
            if not tok:
                return None, None, None
            px = (self.kotak.get_ltps([tok], segment="mcx_fo") or {}).get(tok)
            return px, ts, tok
        except Exception as e:
            log.warning("mcx %s: %s", name, e)
            return None, None, None

    def snapshot(self, name: str) -> dict:
        """Live quote. MCX names: Kotak first, Yahoo fallback. Crypto/FX: Yahoo."""
        spec = SPECS.get(name)
        if not spec:
            return {}
        src = ""
        px = prev = None
        label = spec["name"]
        ccy, unit = spec["ccy"], spec["unit"]
        if spec.get("kind") == "mcx":
            kpx, kts, _tok = self._kotak_mcx(name)
            if kpx:
                px, src = kpx, "Kotak MCX"
                label = kts or f"MCX {spec['mcx']}"
                ccy, unit = spec.get("mcx_ccy", "INR"), spec.get("mcx_unit", "lot")
            else:
                px, prev, _ = self._yahoo(name)
                src = "Yahoo COMEX (Kotak MCX unavailable)"
        else:
            px, prev, _ = self._yahoo(name)
            if spec.get("kind") == "fx":
                src = "Yahoo FX"
            else:
                src = "Yahoo crypto"
        return {"name": name, "spec": spec, "px": px, "prev": prev,
                "src": src, "label": label, "ccy": ccy, "unit": unit}

    def last_price(self, name: str):
        snap = self.snapshot(name)
        return snap.get("px"), snap.get("spec")

    def quote(self, name: str) -> str:
        snap = self.snapshot(name)
        if not snap:
            return "Unknown. Try: GOLD SILVER CRUDE BTC USDINR"
        if not snap.get("px"):
            return f"{name}: price unavailable."
        return (f"{name} ({snap['label']}): {snap['ccy']} {snap['px']:.2f} / {snap['unit']}\n"
                f"Source: {snap['src']}\n"
                "PAPER quote — not a live Kotak order.")

    def history(self, name: str, days: int = 12) -> str:
        spec = SPECS.get(name)
        if not spec:
            return "Unknown. Try: GOLD SILVER BTC USDINR"
        candles = []
        src = ""
        if spec.get("kind") == "mcx" and self.kotak:
            _px, _ts, tok = self._kotak_mcx(name)
            if tok:
                try:
                    candles = self.kotak.daily_history(tok, segment="mcx_fo", days=max(days, 20)) or []
                    src = "Kotak MCX daily"
                except Exception as e:
                    log.warning("mcx hist %s: %s", name, e)
        if not candles:
            candles = web_tools.yahoo_daily(spec["yahoo"], days=max(days, 30)) or []
            src = "Yahoo daily"
        if not candles:
            return f"{name}: no history."
        rows = candles[-min(8, len(candles)):]
        lines = [f"{name} history ({src}) — last {len(rows)} sessions",
                 "Not Sid 44-MA. Not a live order."]
        from datetime import datetime, timezone
        for c in rows:
            ts = c.get("ts", "")
            try:
                n = float(ts)
                if n > 1e9:
                    ts = datetime.fromtimestamp(n, tz=timezone.utc).strftime("%Y-%m-%d")
            except (TypeError, ValueError, OSError):
                ts = str(ts)[:10]
            lines.append(f"  {ts}  o {c['o']:.2f}  h {c['h']:.2f}  "
                         f"l {c['l']:.2f}  c {c['c']:.2f}")
        return "\n".join(lines)

    def research(self, name: str = "") -> str:
        q = ""
        bits = []
        if name and name in SPECS:
            bits.append(self.quote(name))
            bits.append(self.history(name))
            spec = SPECS[name]
            q = f"{spec['name']} {name} India"
            if spec.get("kind") == "mcx":
                q += " MCX"
            elif spec.get("kind") == "crypto":
                q += " crypto"
            else:
                q += " rupee forex"
        else:
            q = "commodity gold silver crude MCX India"
            bits.append(self.scan(names=MCX_NAMES))
        hits = moneycontrol.news(q, 6)
        bits.append(moneycontrol.format_news(hits, "Moneycontrol"))
        bits.append("⚠️ Headlines only — not a buy/sell call. Paper until you say live.")
        return "\n\n".join(bits)

    def scan(self, names=None) -> str:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        names = [n for n in (names or list(SPECS)) if n in SPECS]
        if not names:
            names = list(SPECS)

        def one(n):
            return n, self.snapshot(n)

        got = {}
        with ThreadPoolExecutor(max_workers=6) as pool:
            futs = {pool.submit(one, n): n for n in names}
            for f in as_completed(futs):
                n = futs[f]
                try:
                    got[n] = f.result()[1]
                except Exception as e:
                    got[n] = {"name": n, "px": None, "src": str(e)[:40]}
                    log.warning("scan %s: %s", n, e)
        kinds = {SPECS[n]["kind"] for n in names}
        title = "COMMODITY PAPER SCAN"
        hint = "Type: LTP of GOLD | history GOLD | news GOLD | Buy GOLD 1"
        sess = hours_report("mcx").split("\n")[0]
        if kinds == {"fx"}:
            title = "CURRENCY PAPER SCAN"
            hint = "Type: LTP of USDINR | history USDINR | news USDINR | Buy USDINR 1"
            sess = hours_report("fx").split("\n")[0]
        elif kinds == {"crypto"}:
            title = "CRYPTO PAPER SCAN"
            hint = "Type: LTP of BTC | history BTC | news BTC | Buy BTC 0.01"
            sess = hours_report("crypto").split("\n")[0]
        lines = [
            title,
            sess,
            "MCX: Kotak Neo quotes if logged in (no live order). FX/crypto: Yahoo.",
            "Equity Sid 44-MA is NOT used here. Not auto-buy. PAPER.",
        ]
        for name in names:
            snap = got.get(name) or {}
            spec = SPECS[name]
            px = snap.get("px")
            if not px:
                lines.append(f"{name:7} {spec['name']}: price unavailable")
                continue
            chg = ""
            if snap.get("prev"):
                chg = f"  day {100.0 * (px - snap['prev']) / snap['prev']:+.2f}%"
            held = "  [open]" if name in self.positions else ""
            src = snap.get("src") or ""
            lines.append(
                f"{name:7} {snap.get('label') or spec['name']}: "
                f"{snap.get('ccy', spec['ccy'])} {px:.2f}/{snap.get('unit', spec['unit'])}"
                f"{chg}{held}")
            if src:
                lines.append(f"        {src}")
        lines.append(hint)
        return "\n".join(lines)

    def buy(self, name: str, qty: float) -> str:
        snap = self.snapshot(name)
        spec = snap.get("spec")
        px = snap.get("px")
        if not spec:
            return "Unknown. GOLD SILVER CRUDE NATGAS BTC ETH USDINR"
        if not px:
            return f"{name}: price unavailable."
        qty = float(qty or 1)
        if qty <= 0:
            qty = 1
        if name in self.positions:
            return f"Already holding PAPER {name}. Sell first."
        sl = round(px * 0.98, 4)
        t1 = round(px * 1.05, 4)
        self.positions[name] = {
            "qty": qty, "entry": round(px, 4), "sl": sl, "t1": t1,
            "ccy": snap["ccy"], "unit": snap["unit"], "yahoo": spec["yahoo"],
            "mode": "paper", "src": snap.get("src", ""),
            "date_in": __import__("datetime").datetime.now().strftime("%Y-%m-%d")}
        self.save()
        return (f"🟢 PAPER BUY {name} x{qty:g} @ {snap['ccy']} {px:.2f}/{snap['unit']}\n"
                f"SL {sl:.2f} (-2%) | T1 {t1:.2f} (+5%)\n"
                f"Source: {snap.get('src')}\n"
                "Not sent to Kotak. Not an MCX live order.")

    def sell(self, name: str) -> str:
        p = self.positions.get(name)
        if not p:
            return f"No PAPER {name} position."
        snap = self.snapshot(name)
        px = snap.get("px")
        if not px:
            return "Price unavailable, try later."
        pnl = (px - p["entry"]) * p["qty"]
        self.positions.pop(name, None)
        self.save()
        ccy = p.get("ccy", snap.get("ccy", "USD"))
        return (f"🟢 PAPER EXIT {name} x{p['qty']:g} at {ccy} {px:.2f}  "
                f"PnL {ccy} {pnl:+.2f}")

    def squareoff_all(self) -> str:
        if not self.positions:
            return "Commodity paper: no positions."
        bits = []
        for name in list(self.positions):
            bits.append(self.sell(name))
        return "\n".join(bits)

    def portfolio(self) -> str:
        if not self.positions:
            return "Commodity/FX paper: no positions. Buy GOLD 1 | LTP of BTC"
        lines = ["COMMODITY/FX PAPER (Kotak MCX data if available — no live MCX order)", ""]
        for name, p in self.positions.items():
            snap = self.snapshot(name)
            px = snap.get("px")
            ccy = p.get("ccy", "USD")
            # 'at' not '@' — Telegram turns @4394 into a username link
            if px:
                pnl = (px - p["entry"]) * p["qty"]
                val = px * p["qty"]
                inv = p["entry"] * p["qty"]
                lines.append(f"{name} x{p['qty']:g} at {p['entry']:.2f}  now {px:.2f}")
                lines.append(f"  inv {ccy} {inv:.2f}")
                lines.append(f"  value {ccy} {val:.2f}")
                lines.append(f"  P&L {ccy} {pnl:+.2f}")
            else:
                lines.append(f"{name} x{p['qty']:g} at {p['entry']:.2f}  LTP ?")
            lines.append("")
        lines.append("Live MCX / crypto / FX orders are NOT placed.")
        return "\n".join(lines)

    def tick(self, alert_fn=None):
        msgs = []
        for name in list(self.positions):
            p = self.positions.get(name)
            if not p:
                continue
            px, _ = self.last_price(name)
            if not px:
                continue
            if px <= p.get("sl", 0):
                msgs.append(self.sell(name) + " (STOP-2%)")
            elif px >= p.get("t1", 1e18):
                msgs.append(self.sell(name) + " (TARGET-5%)")
        if alert_fn:
            for m in msgs:
                alert_fn(m)
        return msgs
