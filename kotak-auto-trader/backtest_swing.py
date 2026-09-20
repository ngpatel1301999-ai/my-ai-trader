"""Swing backtest on DAILY data. Measures REAL win-rate. No login needed.

CSV: date,symbol,open,high,low,close,volume   (date like 2026-01-05)
Usage:
  python backtest_swing.py --generate-sample
  python backtest_swing.py --csv swing_sample.csv --sl 2 --t1 5 --t2 8
"""
import argparse
import random
from collections import defaultdict
from datetime import datetime, timedelta

import pandas as pd

from swing import score_setup

TRADING_SYM = "-EQ"


def generate_sample(path="swing_sample.csv", days=180):
    rows, d = [], datetime(2025, 6, 1)
    for sym, start in (("RELIANCE", 3000), ("INFY", 1600), ("TCS", 4200)):
        px, day = start, d
        n = 0
        while n < days:
            if day.weekday() < 5:
                o = px
                px = max(px * (1 + random.uniform(-0.018, 0.022)), 50)
                h, l = max(o, px) * 1.004, min(o, px) * 0.996
                rows.append([day.strftime("%Y-%m-%d"), sym, round(o, 2), round(h, 2),
                             round(l, 2), round(px, 2), random.randint(500000, 4000000)])
                n += 1
            day += timedelta(days=1)
    pd.DataFrame(rows, columns=["date", "symbol", "open", "high", "low", "close", "volume"]
                 ).to_csv(path, index=False)
    print(f"Wrote {path}. NOTE: random data = plumbing test only, NOT real accuracy!")


def run(path, sl_pct, t1_pct, t2_pct, max_hold=10, min_score=70, max_pos=3):
    df = pd.read_csv(path)
    df["date"] = pd.to_datetime(df["date"])
    by_sym = {s: g.sort_values("date").to_dict("records")
              for s, g in df.groupby("symbol")}
    all_dates = sorted(df["date"].unique())
    pos, trades, equity, peak, maxdd = [], [], 0.0, 0.0, 0.0

    for day in all_dates:
        # exits first (use day high/low; if SL+target same day -> SL first = conservative)
        still = []
        for p in pos:
            bars = [b for b in by_sym[p["sym"]] if b["date"] == day]
            if not bars:
                still.append(p)
                continue
            b = bars[0]
            p["days"] += 1
            done = False
            if b["low"] <= p["sl"]:
                px, why = p["sl"], "STOP"
                if not p["t1"] and b["high"] >= p["t1px"]:
                    pass  # SL still first (conservative)
                pnl = (px - p["entry"]) * p["qty"]
                trades.append(pnl)
                equity += pnl
                done = True
            elif not p["t1"] and b["high"] >= p["t1px"]:
                half = p["qty"] // 2
                if half > 0:
                    pnl = (p["t1px"] - p["entry"]) * half
                    trades.append(("part", pnl))
                    equity += pnl
                    p["qty"] -= half
                    p["t1"] = True
                    p["sl"] = p["entry"]  # breakeven
            if not done and p["t1"] and b["high"] >= p["t2px"]:
                pnl = (p["t2px"] - p["entry"]) * p["qty"]
                trades.append(pnl)
                equity += pnl
                done = True
            if not done and p["days"] >= max_hold:
                pnl = (b["close"] - p["entry"]) * p["qty"]
                trades.append(pnl)
                equity += pnl
                done = True
            peak = max(peak, equity)
            maxdd = max(maxdd, peak - equity)
            if not done:
                still.append(p)
        pos = still
        # entries at close
        if len(pos) < max_pos:
            for sym, bars in by_sym.items():
                if len(pos) >= max_pos:
                    break
                if any(p["sym"] == sym for p in pos):
                    continue
                hist = [b for b in bars if b["date"] <= day]
                if len(hist) < 60:
                    continue
                candles = [{"o": b["open"], "h": b["high"], "l": b["low"],
                            "c": b["close"], "v": b["volume"]} for b in hist]
                s, why = score_setup(candles)
                if s >= min_score:
                    e = hist[-1]["close"]
                    pos.append({"sym": sym, "entry": e, "qty": 10, "days": 0,
                                "sl": e * (1 - sl_pct / 100), "t1px": e * (1 + t1_pct / 100),
                                "t2px": e * (1 + t2_pct / 100), "t1": False})
                    print(f"{day.date()} BUY {sym} @{e:.2f} score {s} ({','.join(why)})")

    full = [t for t in trades if not isinstance(t, tuple)]
    parts = [t[1] for t in trades if isinstance(t, tuple)]
    allp = full + parts
    w = [x for x in allp if x > 0]
    l = [x for x in allp if x <= 0]
    print(f"\nTrades={len(allp)} WinRate={100*len(w)/max(len(allp),1):.1f}% "
          f"AvgWin={sum(w)/max(len(w),1):+.0f} AvgLoss={sum(l)/max(len(l),1):+.0f} "
          f"Net={equity:+.0f} MaxDD={maxdd:.0f}")
    print("(Minus brokerage+STT+GST. Use 2+ years REAL data before trusting it.)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="")
    ap.add_argument("--generate-sample", action="store_true")
    ap.add_argument("--sl", type=float, default=2)
    ap.add_argument("--t1", type=float, default=5)
    ap.add_argument("--t2", type=float, default=8)
    a = ap.parse_args()
    if a.generate_sample:
        generate_sample()
    elif a.csv:
        run(a.csv, a.sl, a.t1, a.t2)
    else:
        print("Use --generate-sample or --csv file.csv")
