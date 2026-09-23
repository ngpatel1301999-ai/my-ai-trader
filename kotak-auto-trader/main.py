"""MAIN FILE — Telegram bot + trading loop + web dashboard in ONE process.

Run locally:   python main.py
Run on Render: python main.py            (Start Command)
   or better:  uvicorn main:web_app --host 0.0.0.0 --port $PORT --workers 1

BOT_MODE=swing (default) | intraday | both.  Default = PAPER (fake money).
AI chat + tasks + approvals all flow through the App class below.
No Kotak yet? Bot starts in ASSISTANT MODE (chat/research/tasks work,
trading waits + auto-reconnects). Tip: run with ./supervise.sh.

WEB: "/" serves frontend/index.html, "/health" is for Render,
"/api/status" + "/api/positions" feed the dashboard, "/start" + "/stop"
control the bot thread. The bot auto-starts with the web server
(BOT_AUTOSTART=false to disable).
"""
import difflib
import os
import logging
import sys
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime
from zoneinfo import ZoneInfo

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import SETTINGS
import paths
from kotak_client import KotakClient, BUILD as KC_BUILD
try:
    from build_stamp import BUILD as MAIN_BUILD
except ImportError:
    MAIN_BUILD = "MISSING-build_stamp.py"
from datafeed import CandleBuilder
from strategy import ORBStrategy
from risk import RiskManager
from paper import PaperBroker
from swing import SwingBook, score_setup
try:
    from swing import score_swing
except ImportError:
    def score_swing(candles, style="sid44"):
        s, w = score_setup(candles)
        return s, w, {}
    print("WARNING: swing.py is OLD — copy the new swing.py from the zip (Sid 44-MA + score_swing).")
from tasks import TaskEngine
from ai_agent import Agent, AGENT_BUILD
from telegram_remote import TelegramRemote, send_msg_sync, send_buttons_sync
from commodity import (CommodityBook, pick_name as pick_commodity, wants_commodity,
                       asking_hours, hours_kind, hours_report,
                       FX_NAMES, CRYPTO_NAMES, MCX_NAMES)

IST = ZoneInfo("Asia/Kolkata")

COMMON_SYMBOLS = ["RELIANCE", "INFY", "TCS", "HDFCBANK", "TMPV", "TMCV", "SBIN",
                  "ICICIBANK", "LT", "AXISBANK", "KOTAKBANK", "ITC", "HINDUNILVR",
                  "BHARTIARTL", "MARUTI", "TITAN", "SUNPHARMA", "NTPC", "ONGC"]

LOG_FILE = os.path.join(paths.data_dir(), "trades.log")
_handlers = [logging.StreamHandler()]
try:                      # a read-only disk must never stop the bot
    _handlers.insert(0, logging.FileHandler(LOG_FILE, encoding="utf-8"))
except Exception:
    pass
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=_handlers,
)
log = logging.getLogger("main")

# The Kotak SDK dumps a full JSON blob (request_id, headers, body...) for every
# 401/424/429. kotak_client.py already logs a clean one-line warning for each of
# those, so the raw JSON is just noise that hides real problems in Render logs.
for _noisy in ("neo_api_client", "neo_api_client.rest", "httpx", "httpcore"):
    logging.getLogger(_noisy).setLevel(logging.CRITICAL)


def now_ist() -> datetime:
    return datetime.now(IST)


def past(now: datetime, s: str) -> bool:
    h, m = map(int, s.split(":"))
    return (now.hour, now.minute) >= (h, m)


# ================================================================= App (shared)
class App:
    def __init__(self):
        s = self.s = SETTINGS
        self.live = s.is_live
        self.kotak = KotakClient(s.consumer_key, s.mobile_number, s.ucc,
                                 s.mpin, s.totp_secret, s.exchange_segment)
        self.risk = RiskManager(s.max_daily_loss_rs, s.max_trades_per_day)
        self.tasks = TaskEngine("tasks.json")
        self.comm_tasks = TaskEngine("commodity_tasks.json")
        self.agent = Agent()
        self.agent.quote_hook = self._quote_for_ai   # live Kotak LTP inside AI answers
        self.proposals = {}
        self._pid = 1
        self.universe = []      # [{symbol, trading, token}]
        self.tok2sym = {}
        self.today = None
        self.intra = IntradayEngine(self)
        self.swing = SwingEngine(self)
        self.comm = CommodityBook(self.kotak)
        self.last_symbol = ""

    # ---------------- universe (auto token search, retry-safe) ----------------
    def resolve_universe(self):
        done = {u["symbol"] for u in self.universe}
        for w in SETTINGS.watchlist:
            if w["symbol"] in done:
                continue
            if w.get("token"):
                self.universe.append({"symbol": w["symbol"], "trading": w["trading"],
                                      "token": w["token"]})
                continue
            ts, tok = self.kotak.search_token(w["symbol"])
            if ts and tok:
                log.info("Resolved %s -> %s (%s)", w["symbol"], ts, tok)
                self.universe.append({"symbol": w["symbol"], "trading": ts, "token": tok})
            else:
                log.warning("Could not resolve %s — skipped", w["symbol"])
        self.tok2sym = {u["token"]: u["trading"] for u in self.universe}

    def short_to_trading(self, short: str):
        short = short.upper().replace("-EQ", "")
        for u in self.universe:
            if u["symbol"] == short or u["trading"] == short + "-EQ":
                return u["trading"], u["token"]
        ts, tok = self.kotak.search_token(short)  # try live search for AI symbols
        return ts, tok

    # ---------------- messaging ----------------
    def alert(self, text: str):
        log.info("ALERT: %s", text)
        send_msg_sync(self.s.tg_token, self.s.tg_chat_id, text)

    # ---------------- read commands ----------------
    def cmd_help(self) -> str:
        return ("Type / in Telegram — suggestions (underscore = commodity):\n"
                "/status /pnl /accuracy /stop /resume\n"
                "EQUITY: /portfolio /positions /scan /scan_sid /tasks /squareoff\n"
                "COMMODITY: /portfolio_commodity /positions_commodity\n"
                "  /scan_commodity /scan_currency /scan_crypto /tasks_commodity\n"
                "/buy RELIANCE 5  /buy GOLD 1  /sell SBIN  /sell GOLD\n"
                "/squareoff_commodity   /sl SBIN 985\n"
                "Space also works: /scan commodity  /tasks commodity\n"
                "Plain command = EQUITY only.\n"
                "Chat: research TITAN deeply | news about INFY | is NIFTY a swing buy?\n"
                "Scan: scan  (NSE equity) | scan nifty50 | scan bank | scan sid\n"
                "scan commodity | scan currency | scan crypto  (never NSE Sid)\n"
                "news GOLD | history USDINR | LTP of BTC | research TITAN\n"
                "Or: buy infy below 1500 | square off all | my position\n"
                "Buy TATAPOWER 50 | LTP of RPOWER | square off SBIN if LTP 950\n"
                "square off all if profit 2% or loss 1%\n"
                "square off all if profit 50 | square off all if loss 50\n"
                "cancel all tasks   (checks every 1 sec, not chat)\n"
                "/portfolio  (invested, value, realised, unrealised)\n"
                "PAPER gold/crypto (not Kotak MCX lot): LTP of GOLD | Buy GOLD 1 | Buy BTC 0.01\n"
                "Change SL (real, not chat): /sl SBIN 985")

    def cmd_full_update(self) -> str:
        """Live books snapshot. Never Gemini."""
        now = now_ist().strftime("%Y-%m-%d %H:%M IST")
        bits = [
            f"LIVE UPDATE  {'🔴 LIVE' if self.live else '🟢 PAPER'}  {now}",
            "Numbers from books + LTP — not Gemini.",
            "",
            self.cmd_status(),
            "",
            "— EQUITY —",
            self.cmd_portfolio().rstrip(),
            "",
            self.cmd_positions(include_comm=False).rstrip(),
            "",
            self.cmd_tasks().rstrip(),
        ]
        if getattr(self, "comm", None):
            bits.extend(["", "— COMMODITY / FX PAPER —",
                         self.comm.portfolio().rstrip(),
                         "",
                         self.cmd_comm_tasks().rstrip()])
        bits.append("")
        bits.append("Stay PAPER until you say live. /scan for Sid. /scan_commodity for MCX.")
        return "\n".join(bits)

    def cmd_status(self) -> str:
        kot = "yes" if self.universe else "NO (assistant mode)"
        return (f"Mode: {self.s.bot_mode.upper()} | {'🔴 LIVE' if self.live else '🟢 PAPER'} | "
                f"Kotak: {kot} | Login: {'yes' if self.kotak.logged_in else 'NO'}\n"
                f"AI trade: {'ON' if self.s.ai_may_trade()[0] else 'OFF'}\n{self.risk.summary()}")

    def cmd_pnl(self) -> str:
        parts = []
        if self.s.swing_on or self.swing.book.positions:
            a = self.swing.book.accuracy()
            rows = self._swing_marks()
            # Sum the SAME rows the per-position block prints. The old code read
            # self.swing.unreal(), which used _last_ltps directly - empty at
            # startup - so the headline said "unreal: Rs +0.00" right next to a
            # position showing +152.00. That can not happen any more.
            unreal = sum(r["pnl"] for r in rows)
            missing = [r["ts"] for r in rows if not r.get("ltp_ok")]
            line = (f"SWING realized(all): Rs {a.get('total', 0):+.2f} "
                    f"| unreal: Rs {unreal:+.2f}")
            if missing:
                line += f"\n  ⚠️ LTP nahi mila: {', '.join(missing)}"
            parts.append(line)
        if self.s.intraday_on:
            parts.append(f"INTRADAY today: Rs {self.intra.paper.realized:+.2f} "
                         f"(paper) | unreal Rs {self.intra.paper.unrealized(self.intra.ltps):+.2f}")
        return "\n".join(parts) or "No trades yet."

    def _swing_marks(self) -> list:
        """Per open swing: invested, current value, P&L, LTP.

        LTP resolution used to depend on two things that silently failed:
          * `_last_ltps` being warm - it is EMPTY at startup / after a restart,
          * positions carrying a `token` field - swing.py never saves one, so
            `if p.get("token")` was always False and the fetch never ran.
        Result: open positions showed "LTP ?" and a fake "value Rs 0.00" while
        the stock was perfectly priceable. Now we resolve the token from the
        universe, fetch in ONE batch, retry individually, then fall back to
        Yahoo - and flag `ltp_ok` so the text never prints a misleading 0.00.
        """
        pos = self.swing.book.positions
        if not pos:
            return []
        ltps = dict(getattr(self, "_last_ltps", {}) or {})
        # normalise: make the "-EQ"-free spelling available for every warm key
        for k, v in list(ltps.items()):
            short = str(k).replace("-EQ", "")
            if v and not ltps.get(short):
                ltps[short] = v

        # ---- 1) a token for every position that still has no price ----
        need = {}                          # str(token) -> trading symbol
        for ts, p in pos.items():
            short = str(ts).replace("-EQ", "")
            if ltps.get(ts) or ltps.get(short):
                continue
            tok = p.get("token")
            if not tok:
                try:
                    _ts, tok = self.short_to_trading(short)
                except Exception:
                    tok = None
            if tok:
                p["token"] = tok           # remember it; next call is cheap
                need[str(tok)] = ts

        # ---- 2) one batched quotes call ----
        if need:
            try:
                raw = self.kotak.get_ltps(sorted(need)) or {}
            except Exception as e:
                log.warning("swing LTP batch failed: %s", e)
                raw = {}
            for tok, px in raw.items():
                if not px:
                    continue
                ts = (need.get(str(tok)) or self.tok2sym.get(tok)
                      or self.tok2sym.get(str(tok)))
                if ts:
                    ltps[ts] = px
                    ltps[str(ts).replace("-EQ", "")] = px

        # ---- 3) still missing? single retry, then Yahoo as last resort ----
        import web_tools
        for ts, p in pos.items():
            short = str(ts).replace("-EQ", "")
            if ltps.get(ts) or ltps.get(short):
                continue
            px, src = 0.0, ""
            tok = p.get("token")
            if tok:
                try:
                    px = float(self.kotak.get_ltps([tok]).get(str(tok)) or 0)
                    if px:
                        src = "kotak-retry"
                except Exception:
                    px = 0.0
            if not px:
                try:
                    px = float(web_tools.yahoo_prev_close(short)[1] or 0)
                    if px:
                        src = "yahoo"
                except Exception:
                    px = 0.0
            if px:
                log.info("swing LTP for %s resolved via %s: %.2f", ts, src, px)
                ltps[ts] = px
                ltps[short] = px
        self._last_ltps = ltps

        rows = []
        for ts, p in pos.items():
            ltp = ltps.get(ts) or ltps.get(str(ts).replace("-EQ", "")) or 0
            q = float(p["remaining"])
            inv = float(p["entry"]) * q
            val = (float(ltp) * q) if ltp else 0.0
            pnl = (val - inv) if ltp else 0.0
            pct = (100.0 * pnl / inv) if inv else 0.0
            rows.append({"ts": ts, "p": p, "q": int(q), "entry": float(p["entry"]),
                         "ltp": float(ltp or 0), "inv": inv, "val": val,
                         "pnl": pnl, "pct": pct, "ltp_ok": bool(ltp),
                         "source": p.get("source") or ""})
        return rows

    def _fmt_swing_block(self, r: dict) -> str:
        """One stock, fields on separate lines. Blank line after (join with \\n\\n)."""
        p = r["p"]
        src = " [auto-scan]" if r["source"] == "scan" else ""
        ltp_s = f"{r['ltp']:.2f}" if r["ltp"] else "?"
        if r.get("ltp_ok"):
            val_s = f"  value Rs {r['val']:.2f}"
            pnl_s = f"  P&L {r['pnl']:+.2f} ({r['pct']:+.2f}%)"
        else:
            # A missing price must NEVER be printed as a fake Rs 0.00 / +0.00% -
            # that reads like "position is worthless" when really we just do not
            # have a quote yet.
            val_s = "  value — (LTP nahi mila)"
            pnl_s = "  P&L — (price pending, position safe hai)"
        return (
            f"SW {r['ts']}: B x{r['q']} @{r['entry']:.2f}{src}\n"
            f"  LTP {ltp_s}\n"
            f"  invested Rs {r['inv']:.2f}\n"
            f"{val_s}\n"
            f"{pnl_s}\n"
            f"  SL {p['sl']:.2f} T1 {p['t1px']:.2f} T2 {p['t2px']:.2f} day {p['sessions']}"
        )

    def cmd_positions(self, include_comm: bool = False) -> str:
        rows = self._swing_marks()
        out = [self._fmt_swing_block(r) for r in rows]
        if self.s.intraday_on:
            out.append("INTRADAY: " + (self.intra.cmd_positions() if self.live
                                       else str(self.intra.paper.positions or "none")))
        body = "\n\n".join(out) if out else "No open equity positions."
        if include_comm and getattr(self, "comm", None) and self.comm.positions:
            body += "\n\n" + self.comm.portfolio()
        return body

    def cmd_eod(self) -> str:
        """Spaced EOD: equity block, blank gap, then commodity if any."""
        bits = ["EOD:", "", self.cmd_pnl(), "", self.cmd_positions(include_comm=False)]
        if getattr(self, "comm", None) and self.comm.positions:
            bits.extend(["", self.comm.portfolio()])
        return "\n".join(bits)

    def cmd_portfolio(self) -> str:
        rows = self._swing_marks()
        inv = sum(r["inv"] for r in rows)
        val = sum(r["val"] for r in rows)
        unreal = sum(r["pnl"] for r in rows)
        a = self.swing.book.accuracy()
        real = float(a.get("total") or 0)
        upct = (100.0 * unreal / inv) if inv else 0.0
        lines = [
            f"PORTFOLIO  {'🔴 LIVE' if self.live else '🟢 PAPER'}",
            f"Invested: Rs {inv:.2f}",
            f"Current value: Rs {val:.2f}",
            f"Unrealised P&L: Rs {unreal:+.2f} ({upct:+.2f}%)",
            f"Realised (closed): Rs {real:+.2f}",
            "",
        ]
        if rows:
            for r in rows:
                src = " auto-scan" if r["source"] == "scan" else ""
                ltp_s = f"{r['ltp']:.2f}" if r["ltp"] else "?"
                lines.append(
                    f"{r['ts']} x{r['q']}{src}\n"
                    f"  LTP {ltp_s}\n"
                    f"  invested Rs {r['inv']:.2f}\n"
                    f"  value Rs {r['val']:.2f}\n"
                    f"  P&L {r['pnl']:+.2f} ({r['pct']:+.2f}%)"
                )
                lines.append("")
        else:
            lines.append("No open equity positions.")
            lines.append("")
        ntask = len(self.tasks.open_tasks())
        lines.append(f"Open equity tasks: {ntask}")
        lines.append("(Commodity: /portfolio_commodity)")
        return "\n".join(lines).rstrip() + "\n"

    def cmd_accuracy(self) -> str:
        a = self.swing.book.accuracy()
        if not a.get("n"):
            return "No closed swing trades yet. Backtest first: python backtest_swing.py --csv YOUR.csv"
        exp = (a["winrate"] / 100 * a["avg_win"] + (1 - a["winrate"] / 100) * a["avg_loss"])
        return (f"🎯 Swing accuracy: {a['winrate']:.1f}% ({a['wins']}/{a['n']})\n"
                f"Avg win Rs {a['avg_win']:+.0f} | Avg loss Rs {a['avg_loss']:+.0f}\n"
                f"Expectancy Rs {exp:+.0f}/trade | Total Rs {a['total']:+.0f}")

    def cmd_tasks(self) -> str:
        o = self.tasks.open_tasks()
        if not o:
            return ("EQUITY tasks: none.\nTry: buy 5 reliance if above 3050\n"
                    "Commodity: /tasks_commodity")
        return ("EQUITY tasks:\n" + "\n".join(self.tasks.describe(t) for t in o)
                + "\n\nCommodity: /tasks_commodity")

    def cmd_comm_tasks(self) -> str:
        o = self.comm_tasks.open_tasks()
        if not o:
            return ("COMMODITY tasks: none.\nTry: square off GOLD if LTP 4300\n"
                    "Equity: /tasks")
        return ("COMMODITY tasks:\n"
                + "\n".join(self.comm_tasks.describe(t) for t in o)
                + "\n\nEquity: /tasks")

    def cmd_comm_task(self, text: str) -> str:
        """PAPER commodity task. Never live MCX."""
        import re as _re
        low = (text or "").lower()
        name = pick_commodity(text)
        action = "sell" if name else "squareoff_all"
        mp = _re.search(r"profit\s*:?\s*(\d+(?:\.\d+)?)\s*%", low)
        ml = _re.search(r"loss\s*:?\s*(\d+(?:\.\d+)?)\s*%", low)
        md = _re.search(r"(\d+)\s*(?:totl|total)?\s*working\s*days", low)
        if not md:
            md = _re.search(r"in\s+(\d+)\s*(?:totl|total)?\s*days", low)
        bits = []
        if mp or ml or md:
            def _add(**kw):
                try:
                    return self.comm_tasks.add(**kw)
                except TypeError:
                    kw.pop("from_date", None)
                    return self.comm_tasks.add(**kw)
            if mp:
                pct = float(mp.group(1))
                tid = _add(
                    kind="pnl_pct_above", action=action, symbol=name or "",
                    level=pct, exclusive=True,
                    note=f"{name or 'commodity'} profit >= {pct:g}%")
                bits.append(self.comm_tasks.describe(
                    [x for x in self.comm_tasks.tasks if x["id"] == tid][0]))
            if ml:
                pct = float(ml.group(1))
                tid = _add(
                    kind="pnl_pct_below", action=action, symbol=name or "",
                    level=pct, exclusive=True,
                    note=f"{name or 'commodity'} loss >= {pct:g}%")
                bits.append(self.comm_tasks.describe(
                    [x for x in self.comm_tasks.tasks if x["id"] == tid][0]))
            if md:
                days = int(md.group(1))
                from_date = now_ist().strftime("%Y-%m-%d")
                p = (self.comm.positions or {}).get(name or "")
                if p and p.get("date_in"):
                    from_date = str(p["date_in"])[:10]
                tid = _add(
                    kind="working_days", action=action, symbol=name or "",
                    level=days, exclusive=True, from_date=from_date,
                    note=f"{name or 'commodity'} {days} working days")
                bits.append(self.comm_tasks.describe(
                    [x for x in self.comm_tasks.tasks if x["id"] == tid][0]))
            if bits:
                return ("📌 COMMODITY task (paper) — whichever hits FIRST cancels the others:\n"
                        + "\n".join(bits) + "\n/tasks_commodity")
        nums = [float(x) for x in _re.findall(r"\d+(?:\.\d+)?", text or "")]
        nums = [n for n in nums if n > 0]
        is_loss = bool(_re.search(r"\b(loss|lose|losing)\b", low))
        is_pnl = bool(_re.search(r"\b(profit|pnl|p&l|p/l)\b", low)) or is_loss
        is_ltp = bool(_re.search(r"\b(ltp|cmp|price)\b", low) or "@" in low)
        if is_pnl and not is_ltp:
            if not nums:
                return "Need an amount. Example: square off commodity if loss 50"
            level = nums[-1]
            kind = "pnl_below" if is_loss else "pnl_above"
            tid = self.comm_tasks.add(kind=kind, action="squareoff_all",
                                      level=level, exclusive=True)
            t = [x for x in self.comm_tasks.tasks if x["id"] == tid][0]
            return f"📌 COMMODITY task (paper):\n{self.comm_tasks.describe(t)}\n/tasks_commodity"
        if not name:
            return "Which? Example: square off GOLD if LTP 4300"
        if not nums:
            return "Need a price. Example: square off GOLD if LTP 4300"
        level = nums[-1]
        kind = "price_above" if "above" in low else "price_below"
        action = "squareoff_all" if _re.search(r"\ball\b", low) else "sell"
        if _re.search(r"\bbuy\b", low):
            action = "buy"
        qty = 1.0
        m = _re.search(r"\b(\d+(?:\.\d+)?)\b", low)
        if m and action == "buy":
            qty = float(m.group(1))
        tid = self.comm_tasks.add(kind=kind, action=action, symbol=name,
                                  level=level, qty=qty, exclusive=True)
        t = [x for x in self.comm_tasks.tasks if x["id"] == tid][0]
        return f"📌 COMMODITY task (paper):\n{self.comm_tasks.describe(t)}\n/tasks_commodity"

    def cmd_scan(self) -> str:
        """Read-only scan preview (no orders)."""
        if not self.universe:
            return "🔌 Kotak not connected yet — scan waits. Try `research <stock> deeply` meanwhile!"
        lines = []
        for u in self.universe:
            if u["trading"] in self.swing.book.positions:
                continue
            c = self.kotak.daily_history(u["token"], days=100)
            s, why, meta = score_swing(c, self.s.swing_strategy)
            flag = "YES" if s >= self.s.swing_min_score else "·"
            extra = ""
            if meta.get("sl"):
                extra = f" SL {meta['sl']:.0f} T1 {meta['t1']:.0f}"
            lines.append(f"{flag} {u['symbol']}: {s}{extra} ({','.join(why) or 'weak'})")
        return "🔍 Scan (no orders):\n" + "\n".join(lines)

    def cmd_stop(self, reason) -> str:
        self.risk.engage_kill(reason)
        return "🛑 STOPPED new trades. Exits still auto-managed. /resume to restart."

    def cmd_resume(self) -> str:
        self.risk.release_kill()
        self.risk.stopped_for_day = False
        return "▶️ Resumed."

    def cmd_squareoff(self, reason) -> str:
        out = [self.swing.squareoff_all(reason)]
        if self.s.intraday_on:
            out.append(self.intra.squareoff_all(reason))
        return "\n".join(out)

    def cmd_sl(self, text: str) -> str:
        """Parse '/sl SBIN 985' or 'Update SL 985 of SBIN' and SAVE the book."""
        import re as _re
        raw = (text or "").strip()
        low = raw.lower()
        nums = [float(x) for x in _re.findall(r"\d+(?:\.\d+)?", raw)]
        nums = [n for n in nums if 5 < n < 1_000_000]
        if not nums:
            return "Use: /sl SBIN 985"
        level = nums[-1]
        words = [w.strip(",. ") for w in _re.split(r"\s+", raw) if w.strip()]
        skip = {"update", "set", "change", "move", "trail", "modify", "put",
                "sl", "stop", "loss", "stop-loss", "stoploss", "of", "for",
                "to", "the", "t1", "t2", "target", "/sl", "sl:", "/t1", "/t2"}
        sym = ""
        for w in words:
            u = w.upper().replace("-EQ", "")
            if u.startswith("/"):
                continue
            if w.lower().strip("/") in skip:
                continue
            if _re.fullmatch(r"\d+(?:\.\d+)?", w):
                continue
            if 2 <= len(u) <= 12:
                sym = u
                break
        if not sym:
            return "Which stock? Use: /sl SBIN 985"
        sl = t1 = t2 = None
        if _re.search(r"\b(t1|target\s*1)\b", low) or low.startswith("/t1"):
            t1 = level
        elif _re.search(r"\b(t2|target\s*2)\b", low) or low.startswith("/t2"):
            t2 = level
        else:
            sl = level
        return self.swing.modify_levels(sym, sl=sl, t1=t1, t2=t2)

    def cmd_quote(self, short: str) -> str:
        short = (short or "").upper().replace("-EQ", "").strip()
        if not short or short in ("LTP", "CMP", "QUOTE", "QTY"):
            return "Which stock? Example: LTP of SBIN"
        ts, tok = self.short_to_trading(short) if self.universe else (None, None)
        if tok:
            px = self.kotak.get_ltps([tok]).get(tok)
            if px:
                self.last_symbol = short
                return f"{ts}: Rs {px:.2f}"
        try:
            import web_tools
            _prev, last = web_tools.yahoo_prev_close(short)
            if last:
                self.last_symbol = short
                return f"{short}: Rs {last:.2f}"
        except Exception:
            pass
        return f"Can't find {short}."

    def cmd_open_pnl(self) -> str:
        return self.cmd_portfolio()

    def cmd_cancel_all_tasks(self) -> str:
        n = 0
        for t in list(self.tasks.open_tasks()):
            if self.tasks.cancel(t["id"]):
                n += 1
        return f"Cancelled {n} open task(s).\n{self.cmd_tasks()}"

    def cmd_profit_target(self, text: str) -> str:
        """Save a real task: square off all on profit OR loss (rupees)."""
        import re as _re
        low = (text or "").lower()
        nums = [float(x) for x in _re.findall(r"\d+(?:\.\d+)?", text or "")]
        nums = [n for n in nums if n > 0]
        if not nums:
            return "Need a rupee amount. Example: square off all if loss 50"
        level = nums[-1]
        is_loss = bool(_re.search(r"\b(loss|lose|losing|drawdown)\b", low))
        kind = "pnl_below" if is_loss else "pnl_above"
        note = (f"square off all if open LOSS >= {level:.0f}"
                if is_loss else f"square off all if open profit >= {level:.0f}")
        tid = self.tasks.add(kind=kind, action="squareoff_all", level=level,
                             exclusive=True, note=note)
        t = [x for x in self.tasks.tasks if x["id"] == tid][0]
        return ("📌 Saved (real task, not chat):\n"
                f"{self.tasks.describe(t)}\n"
                "Checks EVERY SECOND in market hours. Paper only.\n"
                "When this fires, other square-off tasks auto-cancel.\n"
                "/tasks to see. cancel all tasks  |  /squareoff to close NOW.")

    def cmd_pct_targets(self, text: str) -> str:
        """square off all if profit 2% or loss 1% — % of invested capital."""
        import re as _re
        low = (text or "").lower()
        mp = _re.search(r"profit\s+(\d+(?:\.\d+)?)\s*%", low) or _re.search(
            r"(\d+(?:\.\d+)?)\s*%\s*(?:profit|gain)", low)
        ml = _re.search(r"loss\s+(\d+(?:\.\d+)?)\s*%", low) or _re.search(
            r"(\d+(?:\.\d+)?)\s*%\s*(?:loss)", low)
        bits = []
        if mp:
            pct = float(mp.group(1))
            tid = self.tasks.add(kind="pnl_pct_above", action="squareoff_all",
                                 level=pct, exclusive=True,
                                 note=f"square off all if book profit >= {pct:g}%")
            bits.append(self.tasks.describe([x for x in self.tasks.tasks if x["id"] == tid][0]))
        if ml:
            pct = float(ml.group(1))
            tid = self.tasks.add(kind="pnl_pct_below", action="squareoff_all",
                                 level=pct, exclusive=True,
                                 note=f"square off all if book loss >= {pct:g}%")
            bits.append(self.tasks.describe([x for x in self.tasks.tasks if x["id"] == tid][0]))
        if not bits:
            return "Need percents. Example: square off all if profit 2% or loss 1%"
        return ("📌 Saved (real tasks, not chat):\n" + "\n".join(bits) +
                "\nChecks EVERY SECOND. % of invested capital (entry x qty).\n"
                "/tasks to see. cancel all tasks  |  /squareoff NOW.")

    def cmd_exit_condition(self, text: str) -> str:
        """square off SBIN if LTP 950  vs  square off all if profit/loss 50 or 2%."""
        import re as _re
        import web_tools
        low = (text or "").lower()
        if "%" in (text or "") or "percent" in low:
            return self.cmd_pct_targets(text)
        is_loss = bool(_re.search(r"\b(loss|lose|losing|drawdown)\b", low))
        is_pnl = bool(_re.search(r"\b(profit|pnl|p&l|p/l)\b", low)) or is_loss
        is_ltp = bool(_re.search(r"\b(ltp|cmp|price)\b", low) or "@" in low)
        if is_pnl and not is_ltp:
            return self.cmd_profit_target(text)
        nums = [float(x) for x in _re.findall(r"\d+(?:\.\d+)?", text or "")]
        nums = [n for n in nums if n > 0]
        if not nums:
            return "Need a price. Example: square off SBIN if LTP 950"
        level = nums[-1]
        sym = web_tools.extract_nse_symbol(text or "")
        if not sym or sym in ("LTP", "CMP", "QTY"):
            if len(self.swing.book.positions) == 1:
                k = next(iter(self.swing.book.positions))
                sym = k.replace("-EQ", "")
            else:
                return "Which stock? Example: square off SBIN if LTP 950"
        ts = self.swing._find_pos(sym)
        kind = "price_below"
        if "above" in low:
            kind = "price_above"
        elif ts:
            entry = self.swing.book.positions[ts]["entry"]
            kind = "price_below" if level < entry else "price_above"
        action = "squareoff_all" if _re.search(r"\ball\b", low) else "sell"
        tid = self.tasks.add(kind=kind, action=action, symbol=sym, level=level,
                             exclusive=True,
                             note=f"{action} {sym} if LTP {kind.split('_')[-1]} {level:g}")
        t = [x for x in self.tasks.tasks if x["id"] == tid][0]
        self.last_symbol = sym
        return ("📌 Saved (real task, not chat):\n"
                f"{self.tasks.describe(t)}\n"
                "Checks EVERY SECOND. Paper only.\n"
                "/tasks to see. /squareoff to close NOW.")

    def cmd_sid_levels(self, text: str) -> str:
        """Sid 44-MA support / T1 / T2 — no Gemini."""
        import web_tools
        import universe
        sym = web_tools.extract_nse_symbol(text or "")
        if not sym or sym in ("LTP", "SID", "CMP"):
            hits = universe.find(text or "", 1)
            sym = hits[0]["symbol"] if hits else ""
        if not sym:
            return "Which stock? Example: sid levels BHARTIARTL"
        self.last_symbol = sym
        ts, tok = self.short_to_trading(sym) if self.universe else (None, None)
        candles = self.kotak.daily_history(tok, days=100) if tok else []
        if not candles:
            candles = web_tools.yahoo_daily(sym, days=90)
        s, why, meta = score_swing(candles, "sid44") if candles else (0, ["no data"], {})
        px = candles[-1]["c"] if candles else None
        lines = [f"Sid 44-MA sniper — {sym}"]
        if px:
            lines.append(f"LTP ~ Rs {px:.2f}")
        if meta.get("ma44"):
            lines.append(f"44-MA: {meta['ma44']:.2f}")
        if meta.get("sl"):
            lines.append(f"Support/SL: {meta['sl']:.2f}")
            lines.append(f"T1 (2R): {meta['t1']:.2f}")
            lines.append(f"T2 (3R): {meta['t2']:.2f}")
        else:
            lines.append("No sniper SL (pattern too wide or penny).")
        lines.append(f"Score: {s}/100 ({', '.join(why) or 'weak'})")
        lines.append("Not auto-buy. Paper only.")
        return "\n".join(lines)

    def cmd_task_link(self, text: str) -> str:
        """If task#3 done then #2 cancel — really write it."""
        import re as _re
        n = 0
        for line in (text or "").splitlines() or [text]:
            m = _re.search(
                r"task\s*#?\s*(\d+)\s*(?:done|complete).{0,24}?(?:then\s+)?#?\s*(\d+)\s*cancel",
                (line or "").lower())
            if not m:
                continue
            a, b = int(m.group(1)), int(m.group(2))
            hit = False
            for t in self.tasks.tasks:
                if t["id"] == a and t.get("status") == "open":
                    lst = list(t.get("cancel_on_done") or [])
                    if b not in lst:
                        lst.append(b)
                    t["cancel_on_done"] = lst
                    hit = True
                    n += 1
            if not hit:
                return f"Task #{a} is not open.\n{self.cmd_tasks()}"
        if n:
            self.tasks.save()
            return ("📌 Linked (real): when a listed task completes, the other cancels.\n"
                    f"{self.cmd_tasks()}")
        return ("Example: If task#3 done then #2 cancel\n"
                "Or: if any one task completes, cancel the other")

    def cmd_tasks_exclusive(self) -> str:
        o = self.tasks.open_tasks()
        if not o:
            return "No open tasks to link."
        for t in o:
            t["exclusive"] = True
        self.tasks.save()
        return ("📌 Real: when ANY of these tasks completes, the others auto-cancel.\n"
                + self.cmd_tasks())

    def cmd_chat_trade(self, text: str) -> str:
        """English buy/sell with qty. Never AI."""
        import re as _re
        import web_tools
        low = (text or "").lower()
        side = "SELL" if _re.search(r"\b(sell|exit)\b", low) and not _re.search(r"\bbuy\b", low) else "BUY"
        qty = 0
        m = _re.search(r"\b(\d+)\s*(?:qty|quantity|shares?|lot|lots)\b", low)
        if not m:
            m = _re.search(r"\b(?:qty|quantity)\s*(?:of\s*)?(\d+)\b", low)
        if not m:
            m = _re.search(r"\b(?:buy|sell)\s+(\d{1,5})\s+[a-z]", low)
        if not m:
            m = _re.search(r"\b(?:buy|sell)\s+[a-z0-9&-]+\s+(\d{1,5})\b", low)
        if m:
            qty = int(m.group(1))
        cleaned = _re.sub(r"@\s*(ltp|cmp)|qty|quantity|shares?|lots?", " ", text or "", flags=_re.I)
        sym = web_tools.extract_nse_symbol(cleaned) or web_tools.extract_nse_symbol(text or "")
        if not sym or sym in ("LTP", "CMP", "QUOTE", "QTY"):
            import universe
            hits = universe.find(cleaned, 1)
            sym = hits[0]["symbol"] if hits else ""
        if not sym:
            sym = self.last_symbol
        if not sym:
            return "Which stock? Example: Buy TATAPOWER 50"
        self.last_symbol = sym
        return self.user_trade(side, sym, qty, "telegram-cmd")

    def cmd_commodity(self, text: str, name: str) -> str:
        """PAPER gold/silver/crypto. Never a Kotak live MCX order."""
        import re as _re
        low = (text or "").lower()
        if _re.search(r"\b(buy|long)\b", low):
            qty = 1.0
            m = _re.search(r"\b(\d+(?:\.\d+)?)\b", low)
            if m:
                qty = float(m.group(1))
            return self.comm.buy(name, qty)
        if _re.search(r"\b(sell|exit|square|squere)\b", low):
            return self.comm.sell(name)
        return self.comm.quote(name)

    def _task_ids(self, text: str) -> list:
        import re as _re
        ids = [int(x) for x in _re.findall(r"#\s*(\d+)", text or "")]
        if ids:
            return ids
        return [int(x) for x in _re.findall(r"\b(\d{1,3})\b", text or "")
                if 1 <= int(x) <= 200]

    def cmd_cancel_tasks(self, text: str, comm: bool = False) -> str:
        """cancle/cancel 2,3,4  |  cancel all  — commodity or equity."""
        import re as _re
        eng = self.comm_tasks if comm else self.tasks
        listing = self.cmd_comm_tasks() if comm else self.cmd_tasks()
        low = (text or "").lower()
        ids = self._task_ids(text)
        if _re.search(r"\ball\b", low) and not _re.search(r"#", text or ""):
            n, done = 0, []
            for t in list(eng.open_tasks()):
                if eng.cancel(t["id"]):
                    n += 1
                    done.append("#%s" % t["id"])
            return ("Cancelled %d %s task(s): %s.\n%s" % (
                n, "commodity" if comm else "equity",
                ", ".join(done) or "none", listing))
        if not ids:
            return "Which task id? Example: cancel 2,3,4 commodity\n" + listing
        bits = []
        for i in ids:
            ok = eng.cancel(i)
            bits.append("#%d cancelled" % i if ok else "#%d not open" % i)
        return "\n".join(bits) + "\n" + listing

    def cmd_commodity_msg(self, text: str) -> str:
        """Any chat with commodity / MCX / GOLD / currency — never NSE Sid."""
        import re as _re
        low = (text or "").lower()
        name = pick_commodity(text)
        if _re.search(r"\b(if|when)\b", low):
            return self.cmd_comm_task(text)
        _cx = _re.search(r"\b(cancel|cancle|delete|remove)\b", low)
        if _cx and ("task" in low or "commodit" in low or _re.search(r"\d+", low)
                    or _re.search(r"\ball\b", low)):
            return self.cmd_cancel_tasks(text, comm=True)
        if "task" in low:
            return self.cmd_comm_tasks()
        if _re.search(r"\b(news|research|headline)\b", low):
            return self.comm.research(name)
        if _re.search(r"\b(history|historical|chart|candles?)\b", low):
            if not name:
                return "Which? history GOLD | history BTC | history USDINR"
            return self.comm.history(name)
        if asking_hours(text):
            return hours_report(hours_kind(text))
        if name:
            return self.cmd_commodity(text, name)
        if _re.search(r"\b(position|portfolio|pnl|p&l|p/l)\b", low):
            return self.comm.portfolio()
        if _re.search(r"\b(sell|exit|square|squere)\b", low):
            return self.comm.squareoff_all()
        if _re.search(r"\b(buy|long)\b", low):
            return ("Which? GOLD SILVER CRUDE BTC USDINR\n"
                    "Example: Buy GOLD 1   (PAPER, not a live MCX order)")
        if _re.search(r"\b(currency|currencies|forex|\bfx\b)", low):
            return self.comm.scan(names=FX_NAMES)
        if _re.search(r"\bcrypto", low):
            return self.comm.scan(names=CRYPTO_NAMES)
        return self.comm.scan(names=MCX_NAMES + CRYPTO_NAMES)


    def cmd_slash(self, text: str) -> str:
        """Plain /cmd = equity. /cmd_commodity or /cmd commodity = commodity."""
        import re as _re
        raw = (text or "").strip()
        body = raw[1:] if raw.startswith("/") else raw
        parts = body.split(None, 1)
        head = parts[0] if parts else ""
        extra = parts[1] if len(parts) > 1 else ""
        if "@" in head:
            head = head.split("@", 1)[0]
        low = (head.replace("_", " ") + (" " + extra if extra else "")).lower().strip()
        bits = low.split()
        cmd = bits[0] if bits else ""
        arg = " ".join(bits[1:])
        is_comm = bool(_re.search(
            r"\b(commodity|commodities|crypto|currency|currencies|forex|mcx)\b",
            low))
        if cmd in ("start", "help"):
            return self.cmd_help()
        if cmd in ("update", "refresh"):
            if is_comm:
                return (self.comm.portfolio() + "\n\n" + self.cmd_comm_tasks())
            return self.cmd_full_update()
        if cmd == "status":
            return self.cmd_status()
        if cmd == "accuracy":
            return self.cmd_accuracy()
        if cmd in ("pnl", "portfolio"):
            return self.comm.portfolio() if is_comm else self.cmd_portfolio()
        if cmd in ("position", "positions"):
            return self.comm.portfolio() if is_comm else self.cmd_positions()
        if cmd in ("task", "tasks"):
            return self.cmd_comm_tasks() if is_comm else self.cmd_tasks()
        if cmd in ("cancel", "cancle"):
            return self.cmd_cancel_tasks(raw, comm=is_comm)
        if cmd == "scan":
            if is_comm and "currency" in low:
                return self.comm.scan(names=FX_NAMES)
            if is_comm and "crypto" in low:
                return self.comm.scan(names=CRYPTO_NAMES)
            if is_comm:
                return self.comm.scan(names=MCX_NAMES + CRYPTO_NAMES)
            if not arg or arg in ("watch", "watchlist", "mine", "equity"):
                return self.cmd_scan()
            return self.agent._scan("scan " + arg)
        if cmd == "stop":
            return self.cmd_stop("Telegram /stop")
        if cmd == "resume":
            return self.cmd_resume()
        if cmd in ("squareoff", "square", "sqroff"):
            if is_comm:
                return self.comm.squareoff_all()
            return self.cmd_squareoff("Telegram /squareoff")
        if cmd in ("sl", "t1", "t2"):
            return self.cmd_sl(raw)
        if cmd in ("buy", "sell"):
            if is_comm or pick_commodity(raw):
                return self.cmd_commodity_msg(raw)
            return self.cmd_chat_trade(raw)
        return self.cmd_help()

    def cmd_chat_route(self, text: str):
        """Real actions that must NEVER go through Gemini. None = use AI."""
        import re as _re
        import web_tools
        raw = (text or "").strip()
        low = raw.lower()
        s = low.strip(" ?!.")
        if not raw:
            return None
        if raw.startswith("/"):
            return self.cmd_slash(raw)
        # "All ai update" / "full update" = live books, never Gemini
        if _re.search(r"\b(model|models|yourself|universe)\b", s):
            pass
        elif (_re.search(r"\b(all\s+ai\s+update|ai\s+update|update\s+all|full\s+update|"
                         r"live\s+update|refresh\s+all|everything\s+update)\b", s)
              or s in ("update", "refresh", "all update")):
            return self.cmd_full_update()
        if _re.fullmatch(r"[ab]", s):
            return ("Say the full command (A/B is too vague):\n"
                    "my position | /tasks | LTP of SBIN | scan sid")
        if wants_commodity(raw):
            return self.cmd_commodity_msg(raw)
        sq = bool(_re.search(r"squ[ae]re\s*off|squareoff|sqroff|close all", low))
        if sq and _re.search(r"\b(if|when)\b", low):
            return self.cmd_exit_condition(raw)
        if sq:
            return self.cmd_squareoff("telegram-chat")
        if s in ("open position", "open positions", "my position", "my positions",
                 "position", "positions") or "open po" in s:
            return self.cmd_positions()
        if s in ("portfolio", "my portfolio", "current pnl", "current p&l",
                 "current p/l"):
            return self.cmd_portfolio()
        if any(w in s for w in ("unreal", "unrealis", "unreleas", "invested",
                                "current value", "current pnl")):
            return self.cmd_portfolio()
        if "position" in s and any(w in s for w in ("pnl", "profit", "p&l", "p/l")):
            return self.cmd_portfolio()
        if s in ("open task", "open tasks", "task", "tasks", "my task", "my tasks"):
            return self.cmd_tasks()
        if s in ("pnl", "profit", "p&l", "p/l"):
            return self.cmd_portfolio()
        if _re.search(r"\b(cancel|cancle|delete|remove)\b", low) and (
                "task" in low or _re.search(r"#\s*\d+", low) or _re.search(r"\ball\b", low)):
            if _re.search(r"\b(if|when|done|complete|then)\b", low):
                return self.cmd_task_link(raw)
            return self.cmd_cancel_tasks(raw, comm=False)
        if (("task" in low or "tasks" in low)
                and _re.search(r"automatic cancel|auto cancel|any one|anyone", low)):
            return self.cmd_tasks_exclusive()
        if (_re.search(r"\b(sl|stop[\s-]?loss|t1|t2)\b", low)
                and _re.search(r"\b(update|set|change|move|trail|modify|put)\b", low)):
            return self.cmd_sl(raw)
        if _re.match(r"(?:please\s+|can you\s+|kindly\s+)*(short|sell short)\b", low):
            return ("Cannot short NSE delivery (CNC). This bot only BUYs for swing.\n"
                    "To exit a long: /sell SBIN  or  /squareoff")
        if (_re.match(r"(?:please\s+|can you\s+|kindly\s+)*(buy|sell)\b", low)
                and not _re.search(r"\b(if|when|above|below)\b", low)):
            return self.cmd_chat_trade(raw)
        if (("sid" in low or "44ma" in low or "44 ma" in low or "bhanushali" in low)
                and any(w in low for w in ("support", "target", "sl", "t1", "t2",
                                           "strategy", "setup", "level"))):
            return self.cmd_sid_levels(raw)
        if _re.search(r"\b(ltp|cmp|quote)\b", low):
            cleaned = _re.sub(r"\b(ltp|cmp|quote|price|of|the|please|what|is|now)\b",
                              " ", raw, flags=_re.I)
            sym = web_tools.extract_nse_symbol(raw)
            if not sym or sym in ("LTP", "CMP", "QUOTE"):
                sym = web_tools.extract_nse_symbol(cleaned)
            if not sym:
                import universe
                hits = universe.find(cleaned or raw, 1)
                sym = hits[0]["symbol"] if hits else ""
            if not sym:
                return "Which stock? Example: LTP of SBIN"
            return self.cmd_quote(sym)
        return None

    # ---------------- AI ----------------
    def _quote_for_ai(self, sym: str) -> dict:
        """Live Kotak LTP for the AI's research answers, so the price shown is
        REAL and current - not a number copied out of a 2-day-old headline."""
        try:
            ts, tok = self.short_to_trading((sym or "").upper())
            if not tok:
                return {}
            raw = self.kotak.get_ltps([tok]) or {}
            px = raw.get(str(tok)) or raw.get(tok)
            if not px:
                return {}
            return {"ltp": round(float(px), 2), "src": "kotak-live", "trading": ts}
        except Exception as e:
            log.warning("live quote for AI failed (%s): %s", sym, e)
            return {}

    def ai_context(self) -> str:
        a = self.swing.book.accuracy()
        return (f"mode={self.s.bot_mode} money={'LIVE-REAL' if self.live else 'PAPER-fake'} "
                f"kotak_connected={bool(self.universe)} swing_open={len(self.swing.book.positions)} "
                f"swing_pnl={a.get('total', 0):+.0f} open_tasks={len(self.tasks.open_tasks())} "
                f"perm_trade={self.s.ai_may_trade()[0]} approval_needed={self.live and self.s.ai_require_approval} "
                f"max_order_rs={self.s.ai_max_order_value_rs}")

    def ai_handle(self, text: str) -> str:
        try:
            fast = self.cmd_chat_route(text)
            if fast is not None:
                return fast
            return self.agent.handle(text, self.ai_context(), self.ai_execute)
        except Exception as e:
            log.exception("agent error: %s", e)
            return f"AI had a problem: {e}\nTry /status or rephrase simply."

    def ai_execute(self, tool: str, args: dict) -> str:
        read = {"status": self.cmd_status, "pnl": self.cmd_portfolio,
                "portfolio": self.cmd_portfolio,
                "positions": self.cmd_positions, "accuracy": self.cmd_accuracy,
                "tasks": self.cmd_tasks, "task_list": self.cmd_tasks,
                "scan": self.cmd_scan, "help": self.cmd_help,
                "full_update": self.cmd_full_update}
        if tool in read:
            return read[tool]()
        if tool == "quote":
            return self.cmd_quote(args.get("symbol", ""))
        if tool == "task_cancel":
            ok = self.tasks.cancel(int(args.get("id", 0)))
            return "Task cancelled." if ok else "Task id not found."
        if tool == "task_create":
            tid = self.tasks.add(kind=args.get("kind", "price_above"),
                                 action=args.get("action", "notify"),
                                 symbol=args.get("symbol", ""),
                                 level=args.get("level", 0), qty=args.get("qty", 0),
                                 note=args.get("note", ""), expires=args.get("expires", ""),
                                 at_time=args.get("at_time", ""))
            t = [x for x in self.tasks.tasks if x["id"] == tid][0]
            return f"📌 Task saved: {self.tasks.describe(t)}\nBot will do it automatically."
        if tool in ("buy", "sell"):
            try:
                qty = int(args.get("qty") or 0)   # 0 = auto-size by risk
            except (TypeError, ValueError):
                qty = 0
            return self.user_trade(tool.upper(), args.get("symbol", ""), qty, "ai")
        if tool == "squareoff":
            sym = (args.get("symbol") or "ALL").upper()
            if sym == "ALL":
                return self.cmd_squareoff("AI squareoff")
            return self.swing.close_by_short(sym, 0, "AI-EXIT")
        if tool in ("modify_sl", "modify_levels"):
            return self.swing.modify_levels(args.get("symbol", ""),
                                            sl=args.get("sl"),
                                            t1=args.get("t1"),
                                            t2=args.get("t2"))
        return f"Unknown tool {tool}"

    # ---------------- user/AI/task trading (always swing-CNC style) ----------------
    def user_trade(self, side: str, short: str, qty: int, source: str) -> str:
        if not self.universe:
            return ("🔌 Kotak not connected yet (assistant mode) — trade NOT placed.\n"
                    "Fix NEO_CONSUMER_KEY in .env + restart (or I auto-retry every 5 min).\n"
                    "Meanwhile I can research, scan web, manage tasks and notes!")
        if side == "SELL":
            return self.swing.close_by_short(short, 0, f"{source}-EXIT")
        ok, why = self.s.ai_may_trade()
        if source in ("ai", "task", "telegram-cmd") and not ok:
            return f"⛔ {why}"
        ok2, why2 = self.risk.can_enter()
        if not ok2:
            return f"⛔ {why2}"
        ts, tok = self.short_to_trading(short)
        if not tok:
            pool = [u["symbol"] for u in self.universe] + COMMON_SYMBOLS
            guess = difflib.get_close_matches(short.upper().replace("-EQ", ""), pool, n=1)
            hint = f" Did you mean {guess[0]}?" if guess else ""
            return f"Can't find {short}.{hint}"
        if ts in self.swing.book.positions:
            return f"Already holding {ts}."
        if len(self.swing.book.positions) >= self.s.max_swing_positions:
            return "Max swing positions reached."
        px = self.kotak.get_ltps([tok]).get(tok)
        if not px:
            return "Live price unavailable, try later."
        user_qty = qty > 0
        if source in ("ai", "task", "telegram-cmd"):
            if qty <= 0:
                qty = self.swing.size_qty(px)   # auto-size from YOUR risk settings
            cap = self.s.ai_max_order_value_rs
            if px * qty > cap and (self.live or not user_qty):
                qty = max(1, int(cap / px))     # auto-fit inside AI value cap
        if self.live and self.s.ai_require_approval and source in ("ai", "telegram-cmd"):
            pid = self._pid
            self._pid += 1
            self.proposals[pid] = {"side": side, "ts": ts, "tok": tok, "qty": qty,
                                   "px": px, "at": time.time()}
            send_buttons_sync(self.s.tg_token, self.s.tg_chat_id,
                              f"⚠️ Approve LIVE BUY?\n{ts} x{qty} @~Rs {px:.2f} (Rs {px*qty:,.0f})", pid)
            return "⚠️ LIVE order needs your Approval — tap ✅/❌ above."
        return self.swing.open_position(ts, tok, qty, px, source)

    def approve(self, pid: int) -> str:
        p = self.proposals.pop(pid, None)
        if not p:
            return "Proposal expired/not found."
        if time.time() - p["at"] > 900:
            return "Proposal expired (15 min). Give the order again."
        return self.swing.open_position(p["ts"], p["tok"], p["qty"], p["px"], "approved")

    def reject(self, pid: int):
        self.proposals.pop(pid, None)

    # ---------------- tasks runner ----------------
    def run_due_tasks(self, prices: dict, now: datetime):
        unreal = 0.0
        invested = 0.0
        for ts, p in self.swing.book.positions.items():
            invested += float(p["entry"]) * float(p["remaining"])
            ltp = prices.get(ts, 0)
            if ltp:
                unreal += (ltp - p["entry"]) * p["remaining"]
        try:
            due = self.tasks.check(prices, now, extra={"unreal": unreal, "invested": invested})
        except TypeError:
            due = self.tasks.check(prices, now)
        for t in due:
            try:
                if t["action"] == "notify":
                    self.alert(f"🔔 TASK #{t['id']}: {t['note'] or self.tasks.describe(t)}")
                    self.tasks.mark_done(t["id"], "notified")
                elif t["action"] == "squareoff_all":
                    r = self.cmd_squareoff(f"TASK #{t['id']}")
                    self.alert(f"🤖 TASK #{t['id']} done: {r}")
                    self.tasks.mark_done(t["id"], r)
                elif t["action"] in ("buy", "sell"):
                    if not self.universe:
                        continue  # keep task OPEN until Kotak connects
                    r = self.user_trade(t["action"].upper(), t["symbol"],
                                        t["qty"] or 0, "task")
                    self.alert(f"🤖 TASK #{t['id']}: {r}")
                    self.tasks.mark_done(t["id"], r)
                self._after_task_done(t)
            except Exception as e:
                self.alert(f"⚠️ TASK #{t['id']} error: {e}")
                self.tasks.mark_done(t["id"], f"error {e}")

    def _after_task_done(self, t: dict):
        """Really cancel linked / exclusive tasks. Never pretend."""
        for cid in t.get("cancel_on_done") or []:
            if self.tasks.cancel(int(cid)):
                self.alert(f"Task #{cid} auto-cancelled (linked to #{t['id']})")
        if t.get("exclusive") or t.get("action") == "squareoff_all":
            for o in list(self.tasks.open_tasks()):
                if o["id"] != t["id"] and self.tasks.cancel(o["id"]):
                    self.alert(f"Task #{o['id']} auto-cancelled (#{t['id']} done)")



    def run_due_comm_tasks(self):
        """PAPER commodity tasks. Never live MCX."""
        if not getattr(self, "comm_tasks", None):
            return
        prices, invested, unreal = {}, 0.0, 0.0
        for name, p in (self.comm.positions or {}).items():
            px, _ = self.comm.last_price(name)
            if px:
                prices[name] = px
                invested += float(p["entry"]) * float(p["qty"])
                unreal += (px - p["entry"]) * float(p["qty"])
        for t in self.comm_tasks.open_tasks():
            sym = t.get("symbol") or ""
            if sym and sym not in prices:
                px, _ = self.comm.last_price(sym)
                if px:
                    prices[sym] = px
        try:
            due = self.comm_tasks.check(prices, now_ist(),
                                        extra={"unreal": unreal, "invested": invested})
        except TypeError:
            due = self.comm_tasks.check(prices, now_ist())
        for t in due:
            try:
                if t["action"] == "notify":
                    self.alert(f"🔔 COMM TASK #{t['id']}: {self.comm_tasks.describe(t)}")
                    self.comm_tasks.mark_done(t["id"], "notified")
                elif t["action"] == "squareoff_all":
                    r = self.comm.squareoff_all()
                    self.alert(f"🤖 COMM TASK #{t['id']}: {r}")
                    self.comm_tasks.mark_done(t["id"], r)
                elif t["action"] == "sell":
                    r = self.comm.sell(t.get("symbol") or "")
                    self.alert(f"🤖 COMM TASK #{t['id']}: {r}")
                    self.comm_tasks.mark_done(t["id"], r)
                elif t["action"] == "buy":
                    r = self.comm.buy(t.get("symbol") or "", t.get("qty") or 1)
                    self.alert(f"🤖 COMM TASK #{t['id']}: {r}")
                    self.comm_tasks.mark_done(t["id"], r)
                if t.get("exclusive"):
                    for o in list(self.comm_tasks.open_tasks()):
                        if o["id"] != t["id"] and self.comm_tasks.cancel(o["id"]):
                            self.alert(f"Comm task #{o['id']} auto-cancelled")
            except Exception as e:
                self.alert(f"⚠️ COMM TASK #{t['id']} error: {e}")
                self.comm_tasks.mark_done(t["id"], f"error {e}")

# ======================================================== SwingEngine
class SwingEngine:
    def __init__(self, app: App):
        self.app = app
        self.book = SwingBook()
        self.new_today = 0
        self.new_day = None
        self.last_scan = None

    def reset_day(self, today):
        if self.new_day != today:
            self.new_day = today
            self.new_today = 0

    def unreal(self) -> float:
        u = 0.0
        ltps = getattr(self.app, "_last_ltps", {})
        for sym, p in self.book.positions.items():
            ltp = ltps.get(sym, 0)
            if ltp:
                u += (ltp - p["entry"]) * p["remaining"]
        return u

    def size_qty(self, entry: float, sl: float = 0) -> int:
        s = self.app.s
        if sl and sl < entry:
            per_share_risk = entry - sl
        else:
            per_share_risk = entry * s.swing_sl_pct / 100
        q = int(s.risk_per_trade_rs / per_share_risk) if per_share_risk > 0 else 1
        q = max(1, min(q, int(s.max_position_value_rs / entry)))
        return q

    def open_position(self, ts: str, tok: str, qty: int, px: float, source: str,
                      sl=None, t1=None, t2=None) -> str:
        s = self.app.s
        if self.live_check_blocked():
            return "⛔ Day stopped / killed."
        if self.live:
            resp = self.app.kotak.place_order(ts, "B", qty, px * 1.001, product="CNC")
            if resp is None:
                return f"❌ LIVE BUY FAILED {ts} — check Neo app."
        sl_px = float(sl) if sl else round(px * (1 - s.swing_sl_pct / 100), 2)
        t1_px = float(t1) if t1 else round(px * (1 + s.swing_t1_pct / 100), 2)
        t2_px = float(t2) if t2 else round(px * (1 + s.swing_t2_pct / 100), 2)
        self.book.positions[ts] = {
            "side": "B", "qty": qty, "remaining": qty, "entry": round(px, 2),
            "token": tok, "date_in": now_ist().strftime("%Y-%m-%d"), "sessions": 0,
            "sl": round(sl_px, 2),
            "t1px": round(t1_px, 2),
            "t2px": round(t2_px, 2),
            "t1_done": False, "mode": "live" if self.live else "paper",
            "style": s.swing_strategy, "source": source}
        self.book.save()
        self.new_today += 1
        self.app.risk.register_entry()
        p = self.book.positions[ts]
        msg = (f"{'🔴 LIVE' if self.live else '🟢 PAPER'} BUY {ts} x{qty} @{px:.2f}\n"
               f"SL {p['sl']:.2f} (-{s.swing_sl_pct}%) | T1 {p['t1px']:.2f} | T2 {p['t2px']:.2f}")
        self.app.alert(msg)
        return msg

    def live_check_blocked(self) -> bool:
        ok, _ = self.app.risk.can_enter()
        return not ok

    @property
    def live(self) -> bool:
        return self.app.live

    def _exit(self, ts: str, px: float, reason: str, qty: int = 0) -> float:
        """Exit qty (0=all). Returns pnl."""
        p = self.book.positions.get(ts)
        if not p or px <= 0:
            return 0.0
        q = p["remaining"] if qty <= 0 else min(qty, p["remaining"])
        if self.live:
            resp = self.app.kotak.place_order(ts, "S", q, px * 0.999, product="CNC")
            if resp is None:
                self.app.alert(f"❌ LIVE SELL FAILED {ts} — SELL MANUALLY IN NEO APP!")
                return 0.0
        pnl = (px - p["entry"]) * q
        p["remaining"] -= q
        if p["remaining"] <= 0:
            self.book.journal({"date_in": p["date_in"], "symbol": ts, "qty": p["qty"],
                               "entry": p["entry"], "date_out": now_ist().strftime("%Y-%m-%d"),
                               "exit": round(px, 2), "reason": reason,
                               "pnl": round(pnl, 2),
                               "pnl_pct": round(100 * (px - p["entry"]) / p["entry"], 2),
                               "win": 1 if px > p["entry"] else 0})
            self.book.positions.pop(ts, None)
        else:
            # partial exit: journal the locked part as its own row
            self.book.journal({"date_in": p["date_in"], "symbol": ts + "(part)", "qty": q,
                               "entry": p["entry"], "date_out": now_ist().strftime("%Y-%m-%d"),
                               "exit": round(px, 2), "reason": reason,
                               "pnl": round(pnl, 2),
                               "pnl_pct": round(100 * (px - p["entry"]) / p["entry"], 2),
                               "win": 1 if pnl > 0 else 0})
        self.book.save()
        self.app.risk.register_exit_pnl(pnl)
        self.app.alert(f"{'🔴 LIVE' if self.live else '🟢 PAPER'} EXIT {ts} x{q} "
                       f"@{px:.2f} ({reason}) P&L {pnl:+.2f}")
        return pnl

    def _find_pos(self, short: str):
        short = (short or "").upper().replace("-EQ", "")
        if not short:
            return None
        for k in self.book.positions:
            ku = k.upper().replace("-EQ", "")
            if ku == short or short in ku or ku in short:
                return k
        ts, _ = self.app.short_to_trading(short)
        if ts in self.book.positions:
            return ts
        return None

    def modify_levels(self, short: str, sl=None, t1=None, t2=None) -> str:
        """Really write SL/T1/T2 into swing_positions.json. Never pretend."""
        ts = self._find_pos(short)
        if not ts:
            open_ = self.app.cmd_positions()
            return f"No open swing position matching {short or '?'}.\nNow: {open_}"
        p = self.book.positions[ts]
        old = (p["sl"], p["t1px"], p["t2px"])
        notes = []
        try:
            if sl is not None and str(sl) != "":
                slf = float(sl)
                if slf <= 0:
                    return "SL must be a positive price."
                if slf >= p["entry"]:
                    notes.append(f"Note: SL {slf:.2f} is at/above entry {p['entry']:.2f}.")
                p["sl"] = round(slf, 2)
            if t1 is not None and str(t1) != "":
                p["t1px"] = round(float(t1), 2)
            if t2 is not None and str(t2) != "":
                p["t2px"] = round(float(t2), 2)
        except (TypeError, ValueError):
            return "Need a number. Example: Update SL 985 of SBIN"
        if (p["sl"], p["t1px"], p["t2px"]) == old:
            return f"Nothing changed on {ts}. Say: Update SL 985 of SBIN"
        self.book.save()
        extra = ("\n" + " ".join(notes)) if notes else ""
        return (f"Saved {ts}: SL {old[0]:.2f}->{p['sl']:.2f} | "
                f"T1 {old[1]:.2f}->{p['t1px']:.2f} | T2 {old[2]:.2f}->{p['t2px']:.2f}"
                f"{extra}\n{self.app.cmd_positions()}")

    def close_by_short(self, short: str, px: float, reason: str) -> str:
        ts, tok = self.app.short_to_trading(short)
        if not ts or ts not in self.book.positions:
            return f"No swing position in {short}."
        if px <= 0:
            px = self.app.kotak.get_ltps([tok]).get(tok, 0)
        if not px:
            return "Price unavailable."
        pnl = self._exit(ts, px, reason)
        return f"Closed {ts} P&L {pnl:+.2f}"

    def guardian_tick(self, ltps: dict):
        """Every minute in market hours: enforce SL/T1/T2 on open positions."""
        self.app._last_ltps = ltps
        for ts in list(self.book.positions.keys()):
            p = self.book.positions.get(ts)
            if not p:
                continue
            ltp = ltps.get(ts, 0)
            if not ltp:
                continue
            if ltp <= p["sl"]:
                self._exit(ts, ltp, "STOP-2%")
            elif not p["t1_done"] and ltp >= p["t1px"]:
                half = p["remaining"] // 2
                if half > 0:
                    self._exit(ts, ltp, "TARGET1-5%(half)")
                    p2 = self.book.positions.get(ts)
                    if p2:
                        p2["sl"] = p2["entry"]  # breakeven
                        p2["t1_done"] = True
                        self.book.save()
                        self.app.alert(f"🔒 {ts}: SL moved to cost (breakeven).")
                else:
                    p["t1_done"] = True  # qty 1: skip partial, hold for T2
                    self.book.save()
            elif p["t1_done"] and ltp >= p["t2px"]:
                self._exit(ts, ltp, "TARGET2-8%")

    def eod_scan(self):
        """3:20 PM job: age positions, time-stop, find new entries."""
        s = self.app.s
        log.info("EOD scan running...")
        ltps = {}
        need = [p["token"] for p in self.book.positions.values()]
        need += [u["token"] for u in self.app.universe]
        raw = self.app.kotak.get_ltps(sorted(set(need))) if need else {}
        for tok, px in raw.items():
            sym = self.app.tok2sym.get(tok)
            if sym:
                ltps[sym] = px
        # age + time stop
        for ts in list(self.book.positions.keys()):
            p = self.book.positions.get(ts)
            if not p:
                continue
            p["sessions"] += 1
            if p["sessions"] >= s.max_hold_days:
                px = ltps.get(ts, 0)
                if px:
                    self._exit(ts, px, f"TIME-STOP {s.max_hold_days}d")
        self.book.save()
        # new entries — OFF unless SWING_AUTO_BUY=true (user must ask to buy)
        if not getattr(s, "swing_auto_buy", False):
            log.info("EOD scan: auto-buy OFF. /scan is preview only.")
            return
        if self.live_check_blocked():
            return
        for u in self.app.universe:
            if len(self.book.positions) >= s.max_swing_positions:
                break
            if self.new_today >= s.max_new_per_day:
                break
            if u["trading"] in self.book.positions:
                continue
            candles = self.app.kotak.daily_history(u["token"], days=100)
            score, why, meta = score_swing(candles, s.swing_strategy)
            log.info("scan %s score %s (%s)", u["symbol"], score, ",".join(why))
            if score >= s.swing_min_score:
                px = ltps.get(u["trading"], 0)
                if not px:
                    continue
                qty = self.size_qty(px, meta.get("sl") or 0)
                if px * qty > s.max_position_value_rs and self.live:
                    qty = max(1, int(s.max_position_value_rs / px))
                self.open_position(u["trading"], u["token"], qty, px, "scan",
                                   sl=meta.get("sl"), t1=meta.get("t1"),
                                   t2=meta.get("t2"))

    def squareoff_all(self, reason: str) -> str:
        if not self.book.positions:
            return "Swing: no positions."
        toks = [p["token"] for p in self.book.positions.values()]
        raw = self.app.kotak.get_ltps(toks)
        n = 0
        for ts in list(self.book.positions.keys()):
            tok = self.book.positions[ts]["token"]
            px = raw.get(tok, 0)
            if px:
                self._exit(ts, px, reason)
                n += 1
        return f"Swing: closed {n} position(s)."


# ======================================================== IntradayEngine (ORB)
class IntradayEngine:
    def __init__(self, app: App):
        self.app = app
        s = self.s = app.s
        self.paper = PaperBroker()
        self.live_pos = {}
        self.ltps = {}
        self.squared_today = False
        self.builders = {}
        self.strats = {}

    def ensure_syms(self):
        for u in self.app.universe:
            ts = u["trading"]
            if ts not in self.builders:
                self.builders[ts] = CandleBuilder(self.s.candle_minutes)
                self.strats[ts] = ORBStrategy(ts, self.s.range_end, self.s.target_r_multiple)

    def reset_day(self):
        self.paper.reset_day()
        self.live_pos = {}
        self.squared_today = False
        for b in self.builders.values():
            b.reset_day()
        for st in self.strats.values():
            st.reset_day()

    def cmd_positions(self) -> str:
        if self.app.live:
            return str(self.live_pos or "none")
        return str(self.paper.positions or "none")

    def poll_once(self, now: datetime):
        self.ensure_syms()
        toks = [u["token"] for u in self.app.universe]
        raw = self.app.kotak.get_ltps(toks)
        for tok, ltp in raw.items():
            sym = self.app.tok2sym.get(tok)
            if sym:
                self.ltps[sym] = ltp
        if not self.ltps:
            return
        for sym, strat in self.strats.items():
            ltp = self.ltps.get(sym, 0)
            if ltp:
                why = strat.check_exit(ltp)
                if why:
                    self.do_exit(sym, ltp, why)
        if past(now, self.s.square_off) and not self.squared_today:
            self.squared_today = True
            self.app.alert("⏰ " + self.squareoff_all("AUTO 15:15"))
            return
        if past(now, self.s.entries_stop):
            return
        for sym, builder in self.builders.items():
            ltp = self.ltps.get(sym, 0)
            if not ltp:
                continue
            done = builder.update(ltp, now.replace(tzinfo=None))
            if done is None:
                continue
            signal = self.strats[sym].on_candle(done)
            if signal:
                ok, reason = self.app.risk.can_enter()
                if not ok:
                    log.info("Entry blocked %s: %s", sym, reason)
                    continue
                self.do_entry(sym, signal, done["c"])

    def do_entry(self, sym, side, price):
        qty = self.s.qty_per_trade
        if self.app.live:
            if self.app.kotak.place_order(sym, side, qty, price, self.s.product_intraday) is None:
                self.app.alert(f"❌ LIVE order FAILED {sym} — check Neo app")
                return
            self.live_pos[sym] = {"side": side, "qty": qty, "entry": price}
            self.app.alert(f"🔴 LIVE {side} {sym} x{qty} @{price:.2f}")
        else:
            self.paper.buy(sym, qty, price) if side == "B" else self.paper.sell(sym, qty, price)
            self.app.alert(f"🟢 PAPER {side} {sym} x{qty} @{price:.2f}")
        self.strats[sym].register_entry(side, price)
        self.app.risk.register_entry()

    def do_exit(self, sym, price, reason):
        strat = self.strats[sym]
        side = strat.side
        if self.app.live:
            out = "S" if side == "B" else "B"
            pos = self.live_pos.get(sym, {})
            qty = pos.get("qty", self.s.qty_per_trade)
            entry = pos.get("entry", price)
            if self.app.kotak.place_order(sym, out, qty, price, self.s.product_intraday) is None:
                self.app.alert(f"❌ LIVE EXIT FAILED {sym} — CLOSE MANUALLY!")
                return
            pnl = ((price - entry) * qty) if side == "B" else ((entry - price) * qty)
            self.live_pos.pop(sym, None)
            self.app.risk.register_exit_pnl(pnl)
            self.app.alert(f"🔴 LIVE EXIT {sym} ({reason}) P&L {pnl:+.2f}")
        else:
            pnl = self.paper.exit(sym, price, reason)
            self.app.risk.register_exit_pnl(pnl)
            self.app.alert(f"🟢 PAPER EXIT {sym} ({reason}) P&L {pnl:+.2f}")
        strat.flat()

    def squareoff_all(self, reason: str) -> str:
        if self.app.live:
            n, note = self.app.kotak.squareoff_all_live(self.s.product_intraday)
            self.live_pos = {}
            for st in self.strats.values():
                st.flat()
            return f"Intraday LIVE: {n} closed. {note}"
        total = self.paper.flat_all(self.ltps, reason)
        for st in self.strats.values():
            st.flat()
        return f"Intraday PAPER closed. P&L {total:+.2f}."


# ================================================================= bot runner
# The bot is ONE object shared by Telegram, the trading loop and the web API.
# It runs in a daemon thread so the web server (main thread) keeps answering
# Render's health checks even while the bot is scanning / trading.
_bot = None                     # App instance (None until started)
_bot_thread = None              # threading.Thread running run_bot_once()
_bot_lock = threading.Lock()    # guards start/stop from the web endpoints
_bot_stop = threading.Event()   # set -> loop exits cleanly
_bot_error = ""                 # last crash reason (shown on the dashboard)
_bot_started_at = None          # datetime the bot was started
_tg = None                      # TelegramRemote thread


def bot_state() -> str:
    if _bot_thread and _bot_thread.is_alive():
        return "running"
    if _bot_error:
        return "crashed"
    if _bot is not None:
        return "stopped"
    return "not_started"


def run_bot_once(app_obj: "App"):
    """Build Telegram remote + run the trading loop until stopped.

    Missing Kotak keys do NOT stop the bot any more: it starts in ASSISTANT
    MODE (chat / research / tasks work) and retries the connection every 5 min.
    """
    global _tg, _bot_error
    try:
        problems = SETTINGS.validate()
        if problems:
            log.warning("Config incomplete -> ASSISTANT MODE. Missing:")
            for pr in problems:
                log.warning("  - %s", pr)
        for w in SETTINGS.warnings():
            log.warning("%s", w)

        app_obj.resolve_universe()
        if app_obj.universe:
            log.info("Universe: %s", [u["trading"] for u in app_obj.universe])
            start_note = f"Watch: {', '.join(u['symbol'] for u in app_obj.universe)}"
        else:
            log.warning("Kotak NOT connected - starting in ASSISTANT MODE.")
            start_note = ("\U0001f50c Assistant mode: Kotak not connected yet.\n"
                          "Chat/research/tasks work. Trading unlocks when the key is fixed.")

        _tg = TelegramRemote(SETTINGS.tg_token, SETTINGS.tg_chat_id, app_obj)
        _tg.start()                       # its own thread + its own asyncio loop
        ready = getattr(_tg, "ready", None)
        if ready is None:
            log.warning("telegram_remote.py is OLD (no ready). Copy the new one.")
            time.sleep(3)
        elif not ready.wait(timeout=25):
            log.warning("Telegram polling slow to start - first messages may be missed")
        tg_ok, tg_why = _tg_status()
        if tg_ok:
            log.info("Telegram remote is live")
        else:
            log.error("Telegram remote NOT live: %s", tg_why)

        paper = "\U0001f7e2 PAPER (fake money - no live orders)"
        mismatch = ""
        if MAIN_BUILD != AGENT_BUILD:
            mismatch = (f"\u26a0\ufe0f COPY MISMATCH: main={MAIN_BUILD} agent={AGENT_BUILD}. "
                        "Overwrite ALL .py files (including build_stamp.py).\n")
        tg_line = ("Type / for commands. Telegram is listening now."
                   if tg_ok else
                   f"\u26a0\ufe0f Telegram OFF: {tg_why}")
        app_obj.alert(f"\U0001f916 Bot started: {SETTINGS.bot_mode.upper()} {paper}\n"
                      f"{mismatch}{start_note}\nBUILD {MAIN_BUILD}  agent={AGENT_BUILD}\n"
                      "Ask anything - I answer THAT question, not a generic news dump.\n"
                      f"{tg_line}")

        loop(app_obj)
    except Exception as e:
        _bot_error = f"{type(e).__name__}: {e}"
        log.exception("BOT CRASHED: %s", e)
    finally:
        # Whatever happened - clean exit, crash or /stop - Telegram must go down
        # too, or it keeps answering while the dashboard shows "stopped".
        tg = _tg
        if tg is not None and not getattr(tg, "stopped", False):
            try:
                tg.stop()
            except Exception as e:
                log.warning("telegram stop in finally failed: %s", e)


def loop(app_obj: "App"):
    """The trading loop. Exits when /stop is pressed (or the process dies)."""
    last_guard = 0.0
    last_kotak_retry = 0.0
    eod_sent = False
    while not _bot_stop.is_set():
        try:
            now = now_ist()
            if now.weekday() >= 5:
                if getattr(app_obj, "comm", None):
                    if app_obj.comm.positions:
                        app_obj.comm.tick(app_obj.alert)
                    app_obj.run_due_comm_tasks()
                    _sleep(30)
                else:
                    _sleep(120)
                continue
            # ---- assistant mode: no Kotak -> chat works, retry connection ----
            if not app_obj.universe:
                if time.time() - last_kotak_retry > 300:
                    last_kotak_retry = time.time()
                    app_obj.resolve_universe()
                    if app_obj.universe:
                        app_obj.alert(f"\U0001f50c Kotak CONNECTED! Watching: "
                                      f"{', '.join(u['symbol'] for u in app_obj.universe)}")
                app_obj.run_due_tasks({}, now)   # time/notify tasks still work
                app_obj.run_due_comm_tasks()
                _sleep(15)
                continue
            if not past(now, SETTINGS.login_time):
                _sleep(30)
                continue
            if not app_obj.kotak.ensure_login():
                log.error("Login failing. Retry in 60s.")
                _sleep(60)
                continue
            if app_obj.today != now.date():
                app_obj.today = now.date()
                app_obj.risk.reset_if_new_day(now)
                app_obj.intra.reset_day()
                app_obj.swing.reset_day(now.date())
                app_obj.swing.last_scan = None
                eod_sent = False
            in_hours = past(now, SETTINGS.market_open) and not past(now, SETTINGS.hard_stop)
            # intraday fast loop
            if SETTINGS.intraday_on and in_hours and not past(now, "15:25"):
                app_obj.intra.poll_once(now)
            # swing guardian + tasks: every 1s when a position or task is open
            hot = bool(app_obj.swing.book.positions) or bool(app_obj.tasks.open_tasks())
            guard_every = 1 if hot else SETTINGS.guardian_seconds
            if SETTINGS.swing_on and in_hours and time.time() - last_guard >= guard_every:
                last_guard = time.time()
                toks = [p["token"] for p in app_obj.swing.book.positions.values()]
                for t in app_obj.tasks.open_tasks():
                    if t.get("symbol"):
                        _, tok = app_obj.short_to_trading(t["symbol"])
                        if tok:
                            toks.append(tok)
                ltps, raw = {}, app_obj.kotak.get_ltps(sorted(set(toks))) if toks else {}
                for tok, px in raw.items():
                    sym = app_obj.tok2sym.get(tok)
                    if sym:
                        ltps[sym] = px
                        ltps[sym.replace("-EQ", "")] = px
                    else:
                        for t in app_obj.tasks.open_tasks():
                            if t.get("symbol"):
                                ltps[t["symbol"]] = px
                                ltps[t["symbol"] + "-EQ"] = px
                app_obj.swing.guardian_tick(ltps)
                app_obj.run_due_tasks(ltps, now)
                app_obj.run_due_comm_tasks()
            # EOD swing scan
            if (SETTINGS.swing_on and past(now, SETTINGS.scan_time)
                    and app_obj.swing.last_scan != now.date()
                    and not past(now, SETTINGS.hard_stop)):
                app_obj.swing.last_scan = now.date()
                app_obj.swing.eod_scan()
            # EOD summary
            if past(now, SETTINGS.hard_stop) and not eod_sent:
                eod_sent = True
                if SETTINGS.intraday_on and not app_obj.intra.squared_today:
                    app_obj.intra.squared_today = True
                    app_obj.alert("\u23f0 " + app_obj.intra.squareoff_all("HARD STOP"))
                app_obj.alert(app_obj.cmd_eod())
            if getattr(app_obj, "comm", None):
                if time.time() - last_guard >= 30:
                    last_guard = time.time()
                    if app_obj.comm.positions:
                        app_obj.comm.tick(app_obj.alert)
                    app_obj.run_due_comm_tasks()
            hot = bool(app_obj.swing.book.positions) or bool(app_obj.tasks.open_tasks())
            if hot and in_hours:
                _sleep(1)
            else:
                _sleep(SETTINGS.poll_seconds if SETTINGS.intraday_on else 5)
        except KeyboardInterrupt:
            log.info("Stopped by user.")
            break
        except Exception as e:
            log.exception("Loop error (keeps running): %s", e)
            _sleep(10)
    log.info("Trading loop stopped.")


def _sleep(seconds: float):
    """Sleep but wake up early when /stop is pressed."""
    _bot_stop.wait(timeout=seconds)


def start_bot() -> tuple:
    """Start the bot thread once. Returns (ok, message)."""
    global _bot, _bot_thread, _bot_error, _bot_started_at, _tg
    with _bot_lock:
        if _bot_thread and _bot_thread.is_alive():
            return False, "Bot is already running."
        _bot_stop.clear()
        _bot_error = ""
        # A stopped TelegramRemote can never be restarted - its asyncio loop is
        # closed. Drop the reference so run_bot_once() builds a fresh one.
        _tg = None
        try:
            _bot = App()
        except Exception as e:
            _bot_error = f"{type(e).__name__}: {e}"
            log.exception("App() build failed")
            return False, f"Bot failed to build: {_bot_error}"
        _bot_started_at = now_ist()
        _bot_thread = threading.Thread(target=run_bot_once, args=(_bot,),
                                       name="trading-bot", daemon=True)
        _bot_thread.start()
        return True, "Bot launched - Telegram + trading loop starting."


def request_stop(timeout: float = 15.0) -> tuple:
    """Stop the trading loop AND close Telegram polling. Returns (ok, message).

    Stopping only the loop used to leave TelegramRemote (its own daemon thread
    with its own asyncio loop) polling forever - the dashboard said "Bot
    stopped" while Telegram kept answering every message.
    """
    global _bot_thread
    with _bot_lock:
        th = _bot_thread
        tg = _tg
        if not th or not th.is_alive():
            # loop already down, but Telegram may still be listening
            if tg is not None and not getattr(tg, "stopped", False):
                tg.stop()
                return True, "Bot was not running - Telegram polling closed."
            return False, "Bot is not running."
        _bot_stop.set()
    th.join(timeout=timeout)
    # close Telegram even if the loop thread was slow to exit
    tg_closed = True
    if tg is not None:
        try:
            tg_closed = tg.stop()
        except Exception as e:
            log.warning("telegram stop failed: %s", e)
            tg_closed = False
    if th.is_alive():
        return True, "Stop requested - loop finishing its current step."
    _bot_thread = None
    return True, ("Bot stopped - Telegram polling closed." if tg_closed
                  else "Bot stopped - WARNING: Telegram thread did not exit")


def main():
    """Console entry: python main.py (bot in the foreground, Ctrl-C to quit)."""
    print(f"BUILD main={MAIN_BUILD} agent={AGENT_BUILD} kotak_client={KC_BUILD}")
    ok, msg = start_bot()
    print(msg)
    if not ok:
        return 1
    try:
        while _bot_thread and _bot_thread.is_alive():
            time.sleep(1)
    except KeyboardInterrupt:
        print("Stopping...")
        request_stop()
    return 0


# ================================================================= web server
FRONTEND_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "frontend")
INDEX_HTML = os.path.join(FRONTEND_DIR, "index.html")


def _truthy(name: str, default: bool = True) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "y")


@asynccontextmanager
async def _lifespan(_app):
    """Start the bot with the web server; stop it on shutdown."""
    if _truthy("BOT_AUTOSTART", True):
        ok, msg = start_bot()
        log.info("autostart: %s", msg)
    else:
        log.info("BOT_AUTOSTART=false - press Start on the dashboard (or POST /start)")
    yield
    request_stop(timeout=5)


web_app = FastAPI(title="AI Auto Trader", version=MAIN_BUILD, lifespan=_lifespan)
web_app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,     # "*" + credentials is rejected by browsers
    allow_methods=["*"],
    allow_headers=["*"],
)


def _tg_status() -> tuple:
    """(connected, human text). Never claims green next to a dead poller."""
    if _tg is None:
        return False, "not started"
    ev = getattr(_tg, "_stop", None)
    if getattr(_tg, "stopped", False) or (ev is not None and ev.is_set()):
        return False, "stopped (polling closed)"
    err = str(getattr(_tg, "error", "") or "")
    if err:
        return False, err
    if not _tg.is_alive():
        return False, "polling thread exited"
    return True, "listening"


def _uptime_s() -> int:
    if not _bot_started_at:
        return 0
    return int((now_ist() - _bot_started_at).total_seconds())


def _positions_snapshot() -> dict:
    """Flat list for the dashboard. Paper books first, Kotak only if LIVE."""
    out = {"positions": [], "source": "paper", "error": ""}
    if _bot is None:
        out["error"] = "bot not started"
        return out
    try:
        for r in _bot._swing_marks():          # equity swing (paper or live)
            out["positions"].append({
                "symbol": str(r["ts"]).replace("-EQ", ""),
                "trading_symbol": r["ts"],
                "type": "swing",
                "qty": r["q"],
                "buy_price": round(r["entry"], 2),
                "ltp": round(r["ltp"], 2),
                "pnl": round(r["pnl"], 2),
                "pnl_pct": round(r["pct"], 2),
                "mode": r["p"].get("mode", "paper"),
            })
    except Exception as e:
        out["error"] = f"equity: {e}"
    try:
        comm = getattr(_bot, "comm", None)
        ltps = dict(getattr(comm, "last_prices", {}) or {}) if comm else {}
        for name, p in (comm.positions.items() if comm else []):
            qty = float(p.get("qty") or 0)
            entry = float(p.get("entry") or 0)
            ltp = float(ltps.get(name) or 0)
            out["positions"].append({
                "symbol": name, "trading_symbol": name, "type": "commodity",
                "qty": qty, "buy_price": entry, "ltp": ltp,
                "pnl": round((ltp - entry) * qty, 2) if ltp else 0.0,
                "pnl_pct": round(100.0 * (ltp - entry) / entry, 2) if (ltp and entry) else 0.0,
                "mode": p.get("mode", "paper"),
            })
    except Exception as e:
        out["error"] = (out["error"] + f" | commodity: {e}").strip(" |")
    if _bot.live:
        out["source"] = "kotak+paper"
        try:
            resp = _bot.kotak.positions()
            rows = resp.get("data") if isinstance(resp, dict) else resp
            out["kotak_raw"] = rows if isinstance(rows, list) else resp
        except Exception as e:
            out["error"] = (out["error"] + f" | kotak: {e}").strip(" |")
    return out


# methods include HEAD: Render (and most uptime monitors) probe with HEAD.
@web_app.api_route("/", methods=["GET", "HEAD"], include_in_schema=False)
def index():
    """Dashboard. 200 on / also keeps Render's health check happy."""
    from fastapi.responses import FileResponse, JSONResponse
    if os.path.exists(INDEX_HTML):
        return FileResponse(INDEX_HTML)
    return JSONResponse({"message": "AI Auto Trader API is running",
                         "hint": "frontend/index.html missing"})


@web_app.api_route("/health", methods=["GET", "HEAD"])
@web_app.api_route("/api/health", methods=["GET", "HEAD"])
def health():
    return {"ok": True, "bot": bot_state(), "uptime_s": _uptime_s()}


@web_app.get("/api/status")
def get_status():
    s = bot_state()
    st = {
        "status": "online" if s == "running" else s,
        "bot": s,
        "paper_trading": (not _bot.live) if _bot else True,
        "mode": SETTINGS.bot_mode,
        "assistant_mode": bool(_bot is not None and not _bot.universe),
        "kotak_connected": bool(_bot is not None and _bot.universe),
        "telegram_connected": _tg_status()[0],
        "telegram": _tg_status()[1],
        "uptime_s": _uptime_s(),
        "build": MAIN_BUILD,
        "error": _bot_error,
    }
    return st


@web_app.get("/api/positions")
async def get_positions():
    from fastapi.concurrency import run_in_threadpool
    try:
        return await run_in_threadpool(_positions_snapshot)   # LTP fetch is blocking
    except Exception as e:
        return {"positions": [], "error": str(e)}


@web_app.get("/api/tasks")
def get_tasks():
    if _bot is None:
        return {"tasks": [], "error": "bot not started"}
    try:
        return {"tasks": _bot.tasks.open_tasks(),
                "commodity_tasks": _bot.comm_tasks.open_tasks()}
    except Exception as e:
        return {"tasks": [], "error": str(e)}


@web_app.get("/api/log")
def get_log(lines: int = 120):
    """Tail trades.log - handy on Render where the disk is not browsable."""
    from fastapi.responses import PlainTextResponse
    try:
        with open(LOG_FILE, encoding="utf-8", errors="replace") as f:
            tail = f.readlines()[-max(1, min(int(lines), 2000)):]
        return PlainTextResponse("".join(tail) or "(log empty)")
    except FileNotFoundError:
        return PlainTextResponse("(no trades.log yet)")


@web_app.post("/start")
def start_endpoint():
    ok, msg = start_bot()
    return {"ok": ok, "message": msg, "bot": bot_state()}


@web_app.post("/stop")
def stop_endpoint():
    ok, msg = request_stop()
    return {"ok": ok, "message": msg, "bot": bot_state()}


def serve_web():
    """One process, one port. Render gives the port in $PORT."""
    port = int(os.getenv("PORT", "10000"))
    host = os.getenv("HOST", "0.0.0.0")
    print(f"BUILD main={MAIN_BUILD} agent={AGENT_BUILD} kotak_client={KC_BUILD}")
    print(f"Web on http://{host}:{port}  |  data dir: {paths.data_dir()}")
    # workers=1 on purpose: more workers = more bots = duplicate Telegram replies
    uvicorn.run(web_app, host=host, port=port, workers=1, log_level="info")


if __name__ == "__main__":
    serve_web()
