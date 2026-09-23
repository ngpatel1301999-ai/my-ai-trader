"""Kotak Neo connection: login, live prices, orders.
Uses the OFFICIAL SDK: pip install kotakneoapi  (import neo_api_client)
Docs: https://github.com/Kotak-Neo/kotak-neo-python

NOTE (Sep 2026): Kotak's script-details/* endpoints (quotes + symbol search)
reject some valid keys (HTTP 424), while login + historical-data work fine.
So this client:
  1. Resolves tokens from a BUILT-IN map verified live against Yahoo prices
     (never trusted blindly; results cached in tokens_verified.json).
  2. Gets LTP from quotes when alive, else from today's 1-min history
     (slightly delayed - fine for swing, flagged in logs).
"""
import json
import logging
import os
import time
from datetime import datetime, timedelta

import pyotp
import web_tools
from neo_api_client import NeoAPI

import paths

BUILD = "2026-09-17d"  # doctor + main print this; mismatch = mixed files

log = logging.getLogger("kotak")

# Built-in NSE tokens (Angel scrip-master, Sep 2026). Live-Yahoo gated.
# TCS=11536 (2955 is KALYANKJIL). TATAMOTORS demerged -> TMPV + TMCV.
NSE_TOKENS = {
    "RELIANCE": ("RELIANCE-EQ", "2885"),
    "INFY": ("INFY-EQ", "1594"),
    "TCS": ("TCS-EQ", "11536"),
    "HDFCBANK": ("HDFCBANK-EQ", "1333"),
    "TMPV": ("TMPV-EQ", "3456"),
    "TMCV": ("TMCV-EQ", "759782"),
    "SBIN": ("SBIN-EQ", "3045"),
    "ICICIBANK": ("ICICIBANK-EQ", "4963"),
    "LT": ("LT-EQ", "11483"),
    "ITC": ("ITC-EQ", "1660"),
    "TITAN": ("TITAN-EQ", "3506"),
}
VERIFIED_FILE = paths.data_path("tokens_verified.json")
FALLBACK_TTL = 30  # seconds: reuse delayed-feed prices within this window


def _walk(obj, keys_wanted):
    """Find values for wanted keys anywhere inside nested dict/list."""
    found = {}
    stack = [obj]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            for k, v in cur.items():
                if k in keys_wanted and k not in found:
                    found[k] = v
                if isinstance(v, (dict, list)):
                    stack.append(v)
        elif isinstance(cur, list):
            stack.extend(cur)
    return found


def extract_ltp(resp, token: str):
    """Quotes response shape can vary; try common price keys. Returns float or None."""
    try:
        lists = []
        if isinstance(resp, dict):
            for k in ("data", "message", "result"):
                if isinstance(resp.get(k), list):
                    lists.append(resp.get(k))
        elif isinstance(resp, list):
            lists.append(resp)
        for lst in lists:
            for row in lst:
                if not isinstance(row, dict):
                    continue
                if str(row.get("instrument_token", row.get("token", ""))) not in ("", str(token)) \
                        and str(row.get("instrument_token", "")) != str(token):
                    continue
                for pk in ("last_traded_price", "ltp", "lastTradedPrice", "last_price", "close", "c"):
                    if row.get(pk) not in (None, "", 0, "0"):
                        return float(row[pk])
        got = _walk(resp, {"last_traded_price", "ltp", "lastTradedPrice", "last_price"})
        for v in got.values():
            try:
                if float(v) > 0:
                    return float(v)
            except (TypeError, ValueError):
                pass
    except Exception as e:
        log.warning("LTP parse issue: %s | raw=%s", e, str(resp)[:300])
    return None


class KotakClient:
    def __init__(self, consumer_key, mobile, ucc, mpin, totp_secret, segment="nse_cm"):
        self.consumer_key = consumer_key
        self.mobile = mobile
        self.ucc = ucc
        self.mpin = mpin
        self.totp_secret = totp_secret
        self.segment = segment
        self.client = None
        self.logged_in = False
        self.login_error = ""
        self.last_login_resp = {}
        self._fb_cache = {}  # token -> (price, timestamp)
        self._fb_warned = 0.0

    def login(self) -> bool:
        """Daily login: TOTP + MPIN. The SDK RETURNS error dicts instead of
        raising, so we verify responses + session tokens. NEVER false-green."""
        self.login_error = ""
        self.last_login_resp = {}
        try:
            if not all([self.consumer_key, self.mobile, self.ucc,
                        self.mpin, self.totp_secret]):
                missing = [n for n, v in
                           (("key", self.consumer_key), ("mobile", self.mobile),
                            ("ucc", self.ucc), ("mpin", self.mpin),
                            ("totp", self.totp_secret)) if not v]
                self.login_error = "missing .env values: " + ",".join(missing)
                self.logged_in = False
                log.error("Kotak login FAILED: %s", self.login_error)
                return False
            self.client = NeoAPI(consumer_key=self.consumer_key, environment="prod")
            totp = pyotp.TOTP(self.totp_secret).now()
            r1 = self.client.totp_login(mobile_number=self.mobile, ucc=self.ucc,
                                        totp=totp)
            self.last_login_resp["totp_login"] = r1
            if isinstance(r1, dict) and "error" in r1:
                self.login_error = f"totp_login rejected: {str(r1.get('error'))[:200]}"
                self.logged_in = False
                log.error("Kotak login FAILED: %s", self.login_error)
                return False
            r2 = self.client.totp_validate(mpin=self.mpin)
            self.last_login_resp["totp_validate"] = r2
            if isinstance(r2, dict) and "error" in r2:
                self.login_error = f"totp_validate rejected: {str(r2.get('error'))[:200]}"
                self.logged_in = False
                log.error("Kotak login FAILED: %s", self.login_error)
                return False
            cfg = getattr(self.client, "configuration", None)
            vt = getattr(cfg, "view_token", None) if cfg else None
            et = getattr(cfg, "edit_token", None) if cfg else None
            if not vt and not et:
                self.login_error = "server gave no session token (silent reject)"
                self.logged_in = False
                log.error("Kotak login FAILED: %s", self.login_error)
                return False
            self.logged_in = True
            log.info("Kotak login OK (view/edit session set)")
            return True
        except Exception as e:
            self.logged_in = False
            self.login_error = str(e)[:200]
            log.error("Kotak login FAILED: %s", e)
            return False

    def ensure_login(self) -> bool:
        if self.logged_in and self.client:
            return True
        for attempt in (1, 2, 3):
            if self.login():
                return True
            time.sleep(5)
        return False

    # ---------------- market data ----------------
    def get_ltps(self, tokens: list, segment: str = None) -> dict:
        """One quotes call for all stocks; missing ones fall back to 1-min
        history (delayed feed). Returns {token: ltp}.
        segment: nse_cm (default) or mcx_fo for commodity DATA (never orders)."""
        out = {}
        segment = segment or self.segment or "nse_cm"
        if not self.ensure_login():
            return out
        try:
            req = [{"instrument_token": str(t), "exchange_segment": segment} for t in tokens]
            resp = self.client.quotes(instrument_tokens=req, quote_type="all")
            rows = []
            if isinstance(resp, dict):
                for k in ("data", "message", "result"):
                    if isinstance(resp.get(k), list):
                        rows = resp.get(k)
                        break
            elif isinstance(resp, list):
                rows = resp
            for row in rows:
                if not isinstance(row, dict):
                    continue
                tok = str(row.get("instrument_token", row.get("token", "")))
                price = None
                for pk in ("last_traded_price", "ltp", "lastTradedPrice", "last_price"):
                    if row.get(pk) not in (None, "", 0, "0"):
                        try:
                            price = float(row[pk])
                            break
                        except (TypeError, ValueError):
                            pass
                if tok and price:
                    out[tok] = price
        except Exception as e:
            log.warning("quotes() failed, using delayed feed: %s", str(e)[:150])
        # fallback for missing tokens via 1-min history
        missing = [str(t) for t in tokens if str(t) not in out]
        if missing:
            if time.time() - self._fb_warned > 600:
                self._fb_warned = time.time()
                log.info("DELAYED FEED on for %d token(s) (quotes endpoint down)", len(missing))
            for tok in missing:
                px = self._ltp_via_history(tok)
                if px:
                    out[tok] = px
        return out

    def _ltp_via_history(self, token: str, segment: str = "nse_cm"):
        """LTP proxy: today's last 1-min close, else last daily close."""
        now = time.time()
        hit = self._fb_cache.get(str(token))
        if hit and now - hit[1] < FALLBACK_TTL:
            return hit[0]
        px = None
        try:
            today = datetime.now().strftime("%Y-%m-%d")
            resp = self._plain_client().historical_data(
                neosymbol=f"{segment}|{token}", interval="1min",
                from_date=today, to_date=today)
            rows = (resp.get("data", {}) or {}).get("candles", [])
            if rows:
                px = float(rows[-1][4])
            else:  # market closed / no today data -> last daily close
                resp = self._plain_client().historical_data(
                    neosymbol=f"{segment}|{token}", interval="D",
                    from_date=(datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d"),
                    to_date=today)
                rows = (resp.get("data", {}) or {}).get("candles", [])
                if rows:
                    px = float(rows[-1][4])
        except Exception as e:
            log.warning("history feed failed for %s: %s", token, str(e)[:120])
        if px:
            self._fb_cache[str(token)] = (px, now)
        return px

    # ---------------- orders (LIMIT at touch price = fills fast in liquid stocks) ----------------
    def place_order(self, symbol: str, side: str, qty: int, price: float,
                    product="MIS", segment="nse_cm"):
        """side: 'B' buy or 'S' sell. Returns broker response (dict) or None."""
        if not self.ensure_login():
            return None
        try:
            px = f"{max(price, 0.05):.2f}"
            resp = self.client.place_order(
                exchange_segment=segment,
                product=product,
                price=px,
                order_type="L",
                quantity=str(int(qty)),
                validity="DAY",
                trading_symbol=symbol,
                transaction_type=side,
            )
            log.info("ORDER %s %s x%d @%s -> %s", side, symbol, qty, px, str(resp)[:300])
            return resp
        except Exception as e:
            log.error("place_order FAILED %s %s: %s", side, symbol, e)
            return None

    # ---------------- book-keeping (shapes vary; used for display + safety) ----------------
    def positions(self):
        try:
            return self.client.positions()
        except Exception as e:
            log.warning("positions() failed: %s", e)
            return None

    def squareoff_all_live(self, product="MIS"):
        """Close all open intraday positions with opposite orders.
        Returns (closed_count, notes). FAILS LOUD — never assumes flat."""
        resp = self.positions()
        if resp is None:
            return 0, "positions() failed — SQUARE OFF MANUALLY IN NEO APP!"
        rows = []
        if isinstance(resp, dict):
            for k in ("data", "message", "result", "positions", "positionDetails"):
                v = resp.get(k)
                if isinstance(v, list):
                    rows = v
                    break
                if isinstance(v, dict):
                    for k2 in ("positions", "positionDetails", "data"):
                        if isinstance(v.get(k2), list):
                            rows = v.get(k2)
                            break
        closed, notes = 0, []
        for r in rows:
            if not isinstance(r, dict):
                continue
            qty = 0
            for qk in ("netQty", "net_qty", "quantity", "qty", "netQuantity", "cfQty"):
                try:
                    if r.get(qk) not in (None, ""):
                        qty = int(float(r[qk]))
                        break
                except (TypeError, ValueError):
                    pass
            sym = r.get("tradingSymbol", r.get("trading_symbol", r.get("symbol", "?")))
            prod = str(r.get("product", r.get("prod", ""))).upper()
            if qty == 0:
                continue
            if product and prod and product not in prod and prod not in ("", "MIS"):
                pass  # still close it — safety first
            side = "S" if qty > 0 else "B"
            px = 0
            for pk in ("last_traded_price", "ltp", "avgPrice", "averagePrice", "buyAvg", "sellAvg"):
                try:
                    if r.get(pk):
                        px = float(r[pk])
                        break
                except (TypeError, ValueError):
                    pass
            if px <= 0:
                tok = str(r.get("instrumentToken", r.get("instrument_token", "")))
                if tok:
                    px = self.get_ltps([tok]).get(tok, 0) or 0
            if px <= 0:
                notes.append(f"{sym}: no price, CLOSE MANUALLY")
                continue
            px = px * (0.998 if side == "S" else 1.002)
            o = self.place_order(sym, side, abs(qty), px, product=product or "MIS")
            if o is not None:
                closed += 1
            else:
                notes.append(f"{sym}: order FAILED, CLOSE MANUALLY")
        return closed, "; ".join(notes) if notes else "ok"

    # ---------------- token search: verified map first, live search fallback ----------------
    def _load_verified(self) -> dict:
        try:
            if os.path.exists(VERIFIED_FILE):
                return json.load(open(VERIFIED_FILE)) or {}
        except Exception:
            pass
        return {}

    def _save_verified(self, short: str, trading: str, token: str):
        try:
            d = self._load_verified()
            d[short] = {"trading": trading, "token": str(token)}
            json.dump(d, open(VERIFIED_FILE, "w"), indent=1)
        except Exception as e:
            log.warning("verified-cache save failed: %s", e)

    def _verify_token(self, short: str, trading: str, token: str) -> bool:
        """Trust a built-in token ONLY if Kotak history close matches Yahoo
        within 5%. Returns False (skip symbol) on any doubt.
        Details of the last check land in self._last_verify for diagnostics."""
        self._last_verify = {"short": short, "token": str(token), "ok": False,
                             "kotak": None, "yahoo": None, "diff": None,
                             "reason": ""}
        try:
            hist = self.daily_history(token, days=8)
            if not hist:
                self._last_verify["reason"] = "no Kotak history"
                log.warning("verify %s: no history for token %s", short, token)
                return False
            kc = hist[-1]["c"]
            prev, last = web_tools.yahoo_prev_close(short)
            ref = prev or last
            if not ref:
                self._last_verify["reason"] = "Yahoo unreachable"
                log.warning("verify %s: Yahoo unreachable - NOT trusting blindly", short)
                return False
            diff = abs(kc - ref) / ref * 100
            self._last_verify.update(kotak=round(kc, 2), yahoo=round(ref, 2),
                                     diff=round(diff, 2))
            log.info("verify %s: kotak=%.2f yahoo=%.2f diff=%.2f%%", short, kc, ref, diff)
            ok = diff <= 5.0
            self._last_verify["ok"] = ok
            if not ok:
                self._last_verify["reason"] = f"diff {diff:.1f}% > 5%"
            return ok
        except Exception as e:
            self._last_verify["reason"] = str(e)[:100]
            log.warning("verify %s failed: %s", short, e)
            return False

    def search_token(self, symbol: str, segment: str = "nse_cm"):
        """Returns (trading_symbol, token) or (None, None).
        Order: verified cache -> built-in map (live-verified) -> live search."""
        short = symbol.upper().replace("-EQ", "")
        cache_key = short if segment == "nse_cm" else f"{segment}:{short}"
        # 1. verified cache
        hit = self._load_verified().get(cache_key) or (
            self._load_verified().get(short) if segment == "nse_cm" else None)
        if hit and hit.get("token"):
            return hit["trading"], str(hit["token"])
        # 2. built-in map + live verification (NSE cash only)
        if short in NSE_TOKENS and segment == "nse_cm":
            ts, tok = NSE_TOKENS[short]
            if self._verify_token(short, ts, tok):
                self._save_verified(short, ts, tok)
                return ts, tok
            log.warning("token-map verify FAILED for %s - trying live search", short)
        # 3. live search (works when Kotak fixes script-details)
        try:
            rows = self._plain_client().search_scrip(
                exchange_segment=segment, symbol=short,
                expiry="", option_type="", strike_price="")
            if isinstance(rows, dict):
                for k in ("data", "message", "result"):
                    if isinstance(rows.get(k), list):
                        rows = rows.get(k)
                        break
            if not isinstance(rows, list) or not rows:
                return None, None
            def _row_ts_tok(r):
                ts = str(r.get("pTrdSymbol") or r.get("trdSymbol") or r.get("pSymbolName") or "")
                tok = str(r.get("pSymbol") or r.get("token") or r.get("instrument_token") or "")
                return ts, tok
            if segment != "nse_cm":
                for r in rows:
                    ts, tok = _row_ts_tok(r)
                    if tok and short in ts.upper().replace(" ", ""):
                        self._save_verified(cache_key, ts, tok)
                        return ts, tok
                ts, tok = _row_ts_tok(rows[0])
                if tok:
                    self._save_verified(cache_key, ts, tok)
                    return ts, tok
                return None, None
            for r in rows:
                ts, tok = _row_ts_tok(r)
                if ts.upper() == short + "-EQ" and tok:
                    self._save_verified(short, ts, tok)
                    return ts, tok
            for r in rows:
                ts, tok = _row_ts_tok(r)
                if ts.upper().endswith("-EQ") and tok:
                    self._save_verified(short, ts, tok)
                    return ts, tok
            ts, tok = _row_ts_tok(rows[0])
            if tok:
                self._save_verified(short, ts, tok)
                return ts, tok
        except Exception as e:
            log.warning("search_token %s failed: %s", symbol, str(e)[:150])
        return None, None

    def daily_history(self, token: str, segment: str = "nse_cm", days: int = 100):
        """Daily candles oldest->newest: [{'ts','o','h','l','c','v'}]."""
        out = []
        try:
            to_d = datetime.now()
            from_d = to_d - timedelta(days=days)
            resp = self._plain_client().historical_data(
                neosymbol=f"{segment}|{token}", interval="D",
                from_date=from_d.strftime("%Y-%m-%d"), to_date=to_d.strftime("%Y-%m-%d"))
            rows = (resp.get("data", {}) or {}).get("candles", []) if isinstance(resp, dict) else []
            for r in rows:
                try:
                    out.append({"ts": r[0], "o": float(r[1]), "h": float(r[2]),
                                "l": float(r[3]), "c": float(r[4]),
                                "v": float(r[5] or 0)})
                except (IndexError, TypeError, ValueError):
                    pass
        except Exception as e:
            log.warning("daily_history %s failed: %s", token, str(e)[:150])
        return out

    # ---------------- session helper ----------------
    def _plain_client(self):
        """Client for search/history. LOGIN-FIRST: Kotak's data endpoints now
        accept the key reliably only with a full session (docs are outdated).
        Falls back to no-session client if login fails (with 5-min cooldown
        so we never hammer Kotak with bad logins)."""
        if self.client and self.logged_in:
            return self.client
        now = time.time()
        if now < getattr(self, "_login_dead_until", 0):
            return self.client or NeoAPI(consumer_key=self.consumer_key,
                                         environment="prod")
        if self.ensure_login():
            return self.client
        self._login_dead_until = now + 300
        if self.client:
            return self.client
        return NeoAPI(consumer_key=self.consumer_key, environment="prod")

    def logout(self):
        try:
            if self.client:
                self.client.logout()
        except Exception:
            pass
        self.logged_in = False
