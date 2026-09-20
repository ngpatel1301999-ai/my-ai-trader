"""Strategy: Opening Range Breakout (ORB) for intraday equity.

Rule (simple):
  - 09:15-09:30 candles make the RANGE (highest high, lowest low).
  - After 09:30: candle CLOSE above range high -> BUY. Below range low -> SELL.
  - Stop-loss = other side of range. Target = entry +/- 1.5 x risk.
  - Only 1 trade per stock per day.
"""
from datetime import time as dtime


class ORBStrategy:
    def __init__(self, symbol: str, range_end: str = "09:30", target_r: float = 1.5):
        self.symbol = symbol
        h, m = map(int, range_end.split(":"))
        self.range_end = dtime(h, m)
        self.target_r = target_r
        self.reset_day()

    def reset_day(self):
        self.range_high = None
        self.range_low = None
        self.range_ready = False
        self.traded = False
        self.side = None          # 'B' or 'S'
        self.entry = 0.0
        self.stop = 0.0
        self.target = 0.0

    # ---------- feed each finished candle ----------
    def on_candle(self, candle: dict):
        """Returns 'B' / 'S' / None."""
        ts = candle["ts"].time() if hasattr(candle["ts"], "time") else candle["ts"]
        if not self.range_ready:
            if ts < self.range_end:
                self.range_high = candle["h"] if self.range_high is None else max(self.range_high, candle["h"])
                self.range_low = candle["l"] if self.range_low is None else min(self.range_low, candle["l"])
                return None
            # first candle at/after range end -> lock the range
            if self.range_high is None:  # bot started late; use this candle as range
                self.range_high, self.range_low = candle["h"], candle["l"]
            self.range_ready = True
            return None
        if self.traded or self.side:
            return None
        if self.range_high is None or self.range_low is None:
            return None
        c = candle["c"]
        if c > self.range_high:
            return "B"
        if c < self.range_low:
            return "S"
        return None

    # ---------- after broker confirms entry ----------
    def register_entry(self, side: str, price: float):
        self.side = side
        self.entry = price
        risk = max(self.range_high - self.range_low, price * 0.001)  # min 0.1% range
        if side == "B":
            self.stop = price - risk
            self.target = price + risk * self.target_r
        else:
            self.stop = price + risk
            self.target = price - risk * self.target_r
        self.traded = True

    # ---------- check every live tick ----------
    def check_exit(self, ltp: float):
        """Returns 'TARGET' / 'STOP' / None."""
        if not self.side or ltp <= 0:
            return None
        if self.side == "B":
            if ltp >= self.target:
                return "TARGET"
            if ltp <= self.stop:
                return "STOP"
        else:
            if ltp <= self.target:
                return "TARGET"
            if ltp >= self.stop:
                return "STOP"
        return None

    def flat(self):
        self.side = None

    def status(self) -> str:
        if not self.range_ready:
            return f"{self.symbol}: forming range"
        pos = f"IN {self.side} @{self.entry:.2f} SL {self.stop:.2f} TGT {self.target:.2f}" if self.side else ("traded-done" if self.traded else "waiting")
        return f"{self.symbol}: R {self.range_low:.2f}-{self.range_high:.2f} | {pos}"
