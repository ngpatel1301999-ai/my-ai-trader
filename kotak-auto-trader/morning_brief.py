"""MORNING BRIEF (video's best feature) — FREE, no Claude/TradingView needed.
Reads Kotak data, scores your watchlist, checks open swing positions,
prints + saves brief_YYYY-MM-DD.md + sends to Telegram.
READ-ONLY: never places orders. Run:  python morning_brief.py  (~8:45 AM)
"""
import json
import logging
import os
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

from config import SETTINGS
from kotak_client import KotakClient
from swing import SwingBook, ema, rsi, score_setup

IST = ZoneInfo("Asia/Kolkata")
logging.basicConfig(level=logging.WARNING)


def tg_send(text: str):
    tok, chat = SETTINGS.tg_token, SETTINGS.tg_chat_id
    if not tok or "PASTE" in tok or not chat:
        return
    try:
        url = f"https://api.telegram.org/bot{tok}/sendMessage"
        data = json.dumps({"chat_id": int(chat), "text": text[:3500]}).encode()
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=20).read()
    except Exception as e:
        print("Telegram send failed:", e)


def main():
    s = SETTINGS
    k = KotakClient(s.consumer_key, s.mobile_number, s.ucc, s.mpin,
                    s.totp_secret, s.exchange_segment)
    today = datetime.now(IST).strftime("%Y-%m-%d")
    if datetime.now(IST).weekday() >= 5:
        print("Weekend — market closed. No brief.")
        return

    # universe
    uni = []
    for w in s.watchlist:
        if w.get("token"):
            uni.append({"symbol": w["symbol"], "trading": w["trading"], "token": w["token"]})
        else:
            ts, tok = k.search_token(w["symbol"])
            if ts and tok:
                uni.append({"symbol": w["symbol"], "trading": ts, "token": tok})
    # LTP (needs login; brief still works without it)
    ltps = {}
    if k.ensure_login():
        raw = k.get_ltps([u["token"] for u in uni])
        t2s = {u["token"]: u["trading"] for u in uni}
        for tok, px in raw.items():
            if tok in t2s:
                ltps[t2s[tok]] = px
    else:
        print("(Login failed — brief without live LTP. Check TOTP/IP.)")

    lines = [f"☀️ MORNING BRIEF {today} ({'LIVE' if s.is_live else 'PAPER'})", ""]
    cands = []
    for u in uni:
        c = k.daily_history(u["token"], days=100)
        score, why = score_setup(c)
        if len(c) < 60:
            lines.append(f"· {u['symbol']}: not enough history")
            continue
        closes = [x["c"] for x in c]
        last = closes[-1]
        e50 = ema(closes, 50)
        dist = 100 * (last - max(x["h"] for x in c[-21:-1])) / last
        ltp = ltps.get(u["trading"], last)
        if score >= s.swing_min_score:
            v = "✅ CANDIDATE"
            cands.append((u["symbol"], score, ltp))
        elif score >= 50:
            v = "👀 WATCH"
        else:
            v = "❌ AVOID"
        lines.append(f"{v} {u['symbol']} {score}/100 @Rs {ltp:.2f} | "
                     f"20D-high {dist:+.1f}% | EMA50 {'above' if last > e50 else 'BELOW'} | "
                     f"RSI {rsi(closes):.0f} | {','.join(why) or 'weak'}")
    # top 3 with levels
    lines.append("")
    if cands:
        lines.append("🎯 TOP CANDIDATES (suggest-only):")
        for sym, sc, px in sorted(cands, key=lambda x: -x[1])[:3]:
            lines.append(f"  {sym} ({sc}): Entry ~{px:.2f} | SL {px*0.98:.2f} | "
                         f"T1 {px*1.05:.2f} | T2 {px*1.08:.2f}")
    else:
        lines.append("No 70+ setups today. Patience = also a position.")
    # open positions
    lines.append("")
    book = SwingBook()
    if book.positions:
        lines.append("📦 OPEN SWING POSITIONS:")
        for sym, p in book.positions.items():
            ltp = ltps.get(sym, p["entry"])
            pnl = (ltp - p["entry"]) * p["remaining"]
            lines.append(f"  {sym}: x{p['remaining']} @{p['entry']:.2f} -> {ltp:.2f} "
                         f"P&L {pnl:+.0f} | SL {p['sl']:.2f} T1 {p['t1px']:.2f} "
                         f"T2 {p['t2px']:.2f} | day {p['sessions']}/{s.max_hold_days}")
    else:
        lines.append("No open swing positions.")
    acc = book.accuracy()
    if acc.get("n"):
        lines.append(f"\n🎯 Accuracy so far: {acc['winrate']:.1f}% ({acc['wins']}/{acc['n']}) "
                     f"Total Rs {acc['total']:+.0f}")

    text = "\n".join(lines)
    print(text)
    with open(f"brief_{today}.md", "w") as f:
        f.write(text)
    tg_send(text)
    print(f"\nSaved brief_{today}.md + sent to Telegram.")


if __name__ == "__main__":
    main()
