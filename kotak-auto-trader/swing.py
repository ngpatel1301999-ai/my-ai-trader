"""SWING engine: buy today, hold up to 2 weeks (10 trading days).

Entry (checked once daily after 3:20 PM scan):
  score >= 70/100: 20-day breakout + above EMA50 + rising trend + high volume
Exit (checked every minute in market hours):
  SL  -2%  |  T1 +5% (sell half, SL -> cost)  |  T2 +8% (sell rest)  |  10-day time stop
NOTE: swing = BUY only. Retail cannot short-sell delivery (CNC) in India.
"""
import csv
import json
import logging
import os
from datetime import datetime

import paths

log = logging.getLogger("swing")

# state lives in paths.data_dir() -> survives restarts when DATA_DIR is a mounted disk
POS_FILE = paths.data_path("swing_positions.json")    # open multi-day positions
TRADES_FILE = paths.data_path("swing_trades.csv")     # closed-trade journal -> accuracy


# ---------------- indicators (plain python, no extra library) ----------------
def ema(values: list, n: int) -> float:
    if len(values) < n:
        return sum(values) / max(len(values), 1)
    k = 2 / (n + 1)
    e = sum(values[:n]) / n
    for v in values[n:]:
        e = v * k + e * (1 - k)
    return e


def rsi(closes: list, n: int = 14) -> float:
    if len(closes) < n + 1:
        return 50.0
    gains, losses = [], []
    for i in range(-n, 0):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0))
        losses.append(max(-d, 0))
    ag, al = sum(gains) / n, sum(losses) / n
    if al == 0:
        return 100.0
    rs = ag / al
    return 100 - 100 / (1 + rs)


def sma(values: list, n: int) -> float:
    if len(values) < n:
        return sum(values) / max(len(values), 1)
    return sum(values[-n:]) / n


def stochastic_k(highs: list, lows: list, closes: list, n: int = 14) -> float:
    if len(closes) < n:
        return 50.0
    hh, ll = max(highs[-n:]), min(lows[-n:])
    if hh <= ll:
        return 50.0
    return 100.0 * (closes[-1] - ll) / (hh - ll)


def _swing_lows(lows: list, order: int = 3) -> list:
    """Indices of local troughs."""
    out = []
    for i in range(order, len(lows) - order):
        if lows[i] <= min(lows[i - order:i]) and lows[i] <= min(lows[i + 1:i + 1 + order]):
            out.append(i)
    return out


def _double_bottom(lows: list, highs: list, lookback: int = 35) -> tuple:
    """(found, pattern_low, neckline). Two similar troughs in lookback."""
    if len(lows) < lookback:
        return False, None, None
    sl = _swing_lows(lows[-lookback:], order=3)
    if len(sl) < 2:
        return False, None, None
    i1, i2 = sl[-2], sl[-1]
    l1, l2 = lows[-lookback:][i1], lows[-lookback:][i2]
    avg = (l1 + l2) / 2
    if avg <= 0 or abs(l1 - l2) / avg > 0.03:
        return False, None, None
    if i2 - i1 < 4:
        return False, None, None
    neck = max(highs[-lookback:][i1:i2 + 1])
    return True, min(l1, l2), neck


def score_sid44(candles: list) -> tuple:
    """Siddharth Bhanushali 44-MA sniper (public rules).
    Returns (score 0-100, reasons, meta{sl,t1,t2,ma44})."""
    empty = {}
    if len(candles) < 60:
        return 0, ["not enough history"], empty
    closes = [c["c"] for c in candles]
    highs = [c["h"] for c in candles]
    lows = [c["l"] for c in candles]
    vols = [c["v"] for c in candles]
    last, last_o = closes[-1], candles[-1]["o"]
    if last < 40:
        return 0, ["penny/illiquid skip"], empty
    ma44 = sma(closes, 44)
    ma44_prev = sma(closes[:-5], 44) if len(closes) > 49 else ma44
    rising = ma44 > ma44_prev
    near = False
    for i in range(-8, 0):
        m = sma(closes[:i], 44) if i != -1 else ma44
        if m and lows[i] <= m * 1.025 and lows[i] >= m * 0.97:
            near = True
            break
    db, pat_low, neck = _double_bottom(lows, highs)
    pattern_low = pat_low or min(lows[-8:])
    green = last >= last_o
    above = last > ma44
    stoch = stochastic_k(highs, lows, closes, 14)
    stoch_was_os = any(stochastic_k(highs[:i], lows[:i], closes[:i], 14) < 30
                       for i in range(-6, 0) if len(closes[:i]) >= 14)
    avg_vol = sum(vols[-21:-1]) / 20 or 1
    vol_ratio = vols[-1] / avg_vol
    score, why = 0, []
    if rising:
        score += 30
        why.append("44MA rising")
    if above:
        score += 20
        why.append("above 44MA")
    if near:
        score += 20
        why.append("pullback to 44")
    if db:
        score += 15
        why.append("double bottom")
    if green and above:
        score += 10
        why.append("green bounce")
    if stoch_was_os or stoch < 35:
        score += 5
        why.append(f"stoch {stoch:.0f}")
    if vol_ratio >= 1.2:
        score += 5
        why.append(f"vol {vol_ratio:.1f}x")
    risk = last - pattern_low
    if risk <= 0 or risk / last > 0.08:
        # SL too tight or wider than 8% — Sid: skip or it is not a sniper
        if risk <= 0:
            return min(score, 40), why + ["no room for SL"], empty
        why.append("SL wide")
        score = min(score, 65)
    sl = round(pattern_low, 2)
    t1 = round(last + 2 * max(risk, last * 0.01), 2)
    t2 = round(last + 3 * max(risk, last * 0.01), 2)
    meta = {"sl": sl, "t1": t1, "t2": t2, "ma44": round(ma44, 2)}
    return min(score, 100), why, meta


def score_swing(candles: list, style: str = "sid44") -> tuple:
    """Dispatcher. Always returns (score, why, meta)."""
    if (style or "sid44").lower() == "classic":
        s, w = score_setup(candles)
        return s, w, {}
    return score_sid44(candles)


def score_setup(candles: list) -> tuple:
    """candles = [{'o','h','l','c','v'}...] daily, oldest->newest. Needs 60+.
    Returns (score 0-100, reasons)."""
    if len(candles) < 60:
        return 0, ["not enough history"]
    closes = [c["c"] for c in candles]
    highs = [c["h"] for c in candles]
    vols = [c["v"] for c in candles]
    last = closes[-1]
    e20, e50 = ema(closes, 20), ema(closes, 50)
    prev20_high = max(highs[-21:-1])
    avg_vol = sum(vols[-21:-1]) / 20 or 1
    vol_ratio = vols[-1] / avg_vol
    r = rsi(closes)
    score, why = 0, []
    if last >= prev20_high:
        score += 35
        why.append("20-day breakout")
    if last > e50:
        score += 20
        why.append("above EMA50")
    if e20 > e50:
        score += 15
        why.append("uptrend")
    if vol_ratio >= 1.3:
        score += 15
        why.append(f"volume {vol_ratio:.1f}x")
    if last > e20:
        score += 10
        why.append("above EMA20")
    if 55 <= r <= 80:
        score += 5
        why.append(f"RSI {r:.0f}")
    return score, why


# ---------------- position book + journal (saved on disk) ----------------
class SwingBook:
    def __init__(self):
        self.positions = {}  # trading_symbol -> dict
        self.load()

    def load(self):
        try:
            if os.path.exists(POS_FILE):
                with open(POS_FILE) as f:
                    self.positions = json.load(f) or {}
        except Exception as e:
            log.warning("positions load failed: %s", e)
            self.positions = {}

    def save(self):
        try:
            with open(POS_FILE, "w") as f:
                json.dump(self.positions, f, indent=1)
        except Exception as e:
            log.warning("positions save failed: %s", e)

    def journal(self, row: dict):
        new = not os.path.exists(TRADES_FILE)
        with open(TRADES_FILE, "a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["date_in", "symbol", "qty", "entry",
                                              "date_out", "exit", "reason", "pnl", "pnl_pct", "win"])
            if new:
                w.writeheader()
            w.writerow(row)

    def accuracy(self) -> dict:
        if not os.path.exists(TRADES_FILE):
            return {"n": 0}
        rows = list(csv.DictReader(open(TRADES_FILE)))
        rows = [r for r in rows if r.get("pnl")]
        if not rows:
            return {"n": 0}
        wins = [float(r["pnl"]) for r in rows if float(r["pnl"]) > 0]
        loss = [float(r["pnl"]) for r in rows if float(r["pnl"]) <= 0]
        tot = sum(float(r["pnl"]) for r in rows)
        return {"n": len(rows), "wins": len(wins),
                "winrate": 100 * len(wins) / len(rows),
                "avg_win": sum(wins) / len(wins) if wins else 0,
                "avg_loss": sum(loss) / len(loss) if loss else 0,
                "total": tot}
