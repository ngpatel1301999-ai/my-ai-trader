"""Turns live tick prices into 5-minute candles. One builder per stock."""
from datetime import datetime


class CandleBuilder:
    def __init__(self, minutes: int = 5):
        self.minutes = minutes
        self.current = None      # candle forming now
        self.done = []           # finished candles

    def _bucket(self, ts: datetime) -> datetime:
        m = (ts.minute // self.minutes) * self.minutes
        return ts.replace(minute=m, second=0, microsecond=0)

    def update(self, price: float, ts: datetime):
        """Feed one price. Returns finished candle dict when a candle closes, else None."""
        if price is None or price <= 0:
            return None
        b = self._bucket(ts)
        if self.current is None or self.current["ts"] != b:
            finished = self.current
            if finished is not None:
                self.done.append(finished)
            self.current = {"ts": b, "o": price, "h": price, "l": price, "c": price}
            return finished
        c = self.current
        c["h"] = max(c["h"], price)
        c["l"] = min(c["l"], price)
        c["c"] = price
        return None

    def reset_day(self):
        self.current = None
        self.done = []
