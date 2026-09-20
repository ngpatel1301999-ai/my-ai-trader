"""Offline test of the ORB strategy on old 1-minute data. No login needed.

CSV format: timestamp,symbol,open,high,low,close   (timestamp like 2026-09-01 09:15)
Usage:
  python backtest.py --generate-sample
  python backtest.py --csv sample_1min.csv
"""
import argparse
import random
from collections import defaultdict
from datetime import datetime, timedelta

import pandas as pd

from strategy import ORBStrategy


def generate_sample(path="sample_1min.csv", days=5):
    rows = []
    base = datetime(2026, 9, 1, 9, 15)
    for d in range(days):
        px = 1500.0
        for m in range(375):  # 9:15 -> 15:30
            ts = base + timedelta(days=d, minutes=m)
            if ts.weekday() >= 5:
                continue
            o = px
            drift = random.uniform(-1.2, 1.2)
            px = max(px + drift, 100)
            h, l = max(o, px) + random.random(), min(o, px) - random.random()
            rows.append([ts.strftime("%Y-%m-%d %H:%M"), "RELIANCE-EQ",
                         round(o, 2), round(h, 2), round(l, 2), round(px, 2)])
    pd.DataFrame(rows, columns=["timestamp", "symbol", "open", "high", "low", "close"]
                 ).to_csv(path, index=False)
    print(f"Sample written: {path} ({len(rows)} rows). NOTE: random data, only for plumbing test.")


def to_5min(df: pd.DataFrame):
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.sort_values("timestamp")
    out = []
    for (day, sym), g in df.groupby([df["timestamp"].dt.date, "symbol"]):
        g = g.set_index("timestamp").sort_index()
        r = g.resample("5min").agg({"open": "first", "high": "max", "low": "min",
                                    "close": "last", "symbol": "first"}).dropna()
        for ts, row in r.iterrows():
            out.append({"ts": ts.to_pydatetime(), "symbol": sym, "o": row.open,
                        "h": row.high, "l": row.low, "c": row.close})
    return out


def run_backtest(path: str):
    df = pd.read_csv(path)
    candles = to_5min(df)
    by_day = defaultdict(list)
    for c in candles:
        by_day[c["ts"].date()].append(c)

    total_pnl, wins, losses, trades = 0.0, 0, 0, 0
    for day in sorted(by_day):
        for sym in {c["symbol"] for c in by_day[day]}:
            st = ORBStrategy(sym)
            day_candles = sorted([c for c in by_day[day] if c["symbol"] == sym],
                                 key=lambda x: x["ts"])
            for c in day_candles:
                sig = st.on_candle(c)
                if sig and not st.side:
                    st.register_entry(sig, c["c"])
                    print(f"{day} {sym} {sig} @{c['c']:.2f} SL {st.stop:.2f} TGT {st.target:.2f}")
                if st.side:
                    # intra-candle SL/target check
                    if st.side == "B":
                        hit_t = c["h"] >= st.target
                        hit_s = c["l"] <= st.stop
                        exit_px = c["c"] if (c["ts"].hour, c["ts"].minute) >= (15, 15) else None
                    else:
                        hit_t = c["l"] <= st.target
                        hit_s = c["h"] >= st.stop
                        exit_px = c["c"] if (c["ts"].hour, c["ts"].minute) >= (15, 15) else None
                    if hit_s and hit_t:
                        exit_px = st.stop  # both hit: assume worst
                    elif hit_s:
                        exit_px = st.stop
                    elif hit_t:
                        exit_px = st.target
                    if exit_px:
                        pnl = (exit_px - st.entry) if st.side == "B" else (st.entry - exit_px)
                        total_pnl += pnl
                        trades += 1
                        wins += 1 if pnl > 0 else 0
                        losses += 1 if pnl <= 0 else 0
                        print(f"   exit @{exit_px:.2f} P&L {pnl:+.2f}")
                        st.flat()
                        st.traded = True
            # force exit at day end if still open
            if st.side:
                pnl = (day_candles[-1]["c"] - st.entry) if st.side == "B" else (st.entry - day_candles[-1]["c"])
                total_pnl += pnl
                trades += 1
                wins += 1 if pnl > 0 else 0
                losses += 1 if pnl <= 0 else 0
                print(f"   EOD exit P&L {pnl:+.2f}")
    print(f"\nRESULT: trades={trades} wins={wins} losses={losses} total P&L (per share)={total_pnl:+.2f}")
    print("(Minus brokerage + STT + GST in real life. Get REAL 1-min data for true test.)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="")
    ap.add_argument("--generate-sample", action="store_true")
    a = ap.parse_args()
    if a.generate_sample:
        generate_sample()
    elif a.csv:
        run_backtest(a.csv)
    else:
        print("Use --generate-sample or --csv file.csv")
