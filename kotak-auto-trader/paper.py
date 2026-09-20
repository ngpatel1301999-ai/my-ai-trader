"""Fake-money broker. Same trades, Rs 0 risk. Uses REAL live prices."""


class PaperBroker:
    def __init__(self):
        self.positions = {}   # symbol -> {'side','qty','entry'}
        self.realized = 0.0
        self.trades = []      # history strings

    def reset_day(self):
        self.positions = {}
        self.realized = 0.0
        self.trades = []

    def buy(self, symbol, qty, price):
        self.positions[symbol] = {"side": "B", "qty": qty, "entry": price}
        self.trades.append(f"PAPER BUY {symbol} x{qty} @{price:.2f}")

    def sell(self, symbol, qty, price):
        self.positions[symbol] = {"side": "S", "qty": qty, "entry": price}
        self.trades.append(f"PAPER SELL {symbol} x{qty} @{price:.2f}")

    def exit(self, symbol, price, reason=""):
        p = self.positions.pop(symbol, None)
        if not p:
            return 0.0
        if p["side"] == "B":
            pnl = (price - p["entry"]) * p["qty"]
        else:
            pnl = (p["entry"] - price) * p["qty"]
        self.realized += pnl
        self.trades.append(f"PAPER EXIT {symbol} @{price:.2f} ({reason}) P&L {pnl:+.2f}")
        return pnl

    def unrealized(self, ltps: dict) -> float:
        u = 0.0
        for sym, p in self.positions.items():
            ltp = ltps.get(sym, 0)
            if not ltp:
                continue
            if p["side"] == "B":
                u += (ltp - p["entry"]) * p["qty"]
            else:
                u += (p["entry"] - ltp) * p["qty"]
        return u

    def flat_all(self, ltps: dict, reason="SQUAREOFF"):
        total = 0.0
        for sym in list(self.positions.keys()):
            total += self.exit(sym, ltps.get(sym, 0) or 0, reason)
        return total
