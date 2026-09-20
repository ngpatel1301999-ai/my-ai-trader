"""Risk manager = safety guard. Blocks trades when limits hit."""
import os
from datetime import datetime

KILL_FILE = "KILLSWITCH"


class RiskManager:
    def __init__(self, max_daily_loss_rs: float, max_trades_per_day: int):
        self.max_daily_loss_rs = max_daily_loss_rs
        self.max_trades_per_day = max_trades_per_day
        self.day = None
        self.realized_pnl = 0.0
        self.trades_today = 0
        self.stopped_for_day = False
        self.stop_reason = ""

    # ---------- daily reset ----------
    def reset_if_new_day(self, now: datetime):
        today = now.date()
        if self.day != today:
            self.day = today
            self.realized_pnl = 0.0
            self.trades_today = 0
            self.stopped_for_day = False
            self.stop_reason = ""
            if os.path.exists(KILL_FILE):
                os.remove(KILL_FILE)

    # ---------- kill switch ----------
    @staticmethod
    def kill_on() -> bool:
        return os.path.exists(KILL_FILE)

    @staticmethod
    def engage_kill(reason: str = ""):
        with open(KILL_FILE, "w") as f:
            f.write(reason or "manual stop")

    @staticmethod
    def release_kill():
        if os.path.exists(KILL_FILE):
            os.remove(KILL_FILE)

    # ---------- checks ----------
    def can_enter(self) -> tuple:
        """Returns (True, '') or (False, reason)."""
        if self.kill_on():
            return False, "KILL SWITCH is ON (/resume to release)"
        if self.stopped_for_day:
            return False, f"Stopped for today: {self.stop_reason}"
        if self.trades_today >= self.max_trades_per_day:
            return False, f"Max trades/day ({self.max_trades_per_day}) reached"
        if self.realized_pnl <= -abs(self.max_daily_loss_rs):
            self.stopped_for_day = True
            self.stop_reason = f"Daily loss limit hit ({self.realized_pnl:.0f})"
            return False, self.stop_reason
        return True, ""

    def register_entry(self):
        self.trades_today += 1

    def register_exit_pnl(self, pnl: float):
        self.realized_pnl += pnl
        if self.realized_pnl <= -abs(self.max_daily_loss_rs):
            self.stopped_for_day = True
            self.stop_reason = f"Daily loss limit hit ({self.realized_pnl:.0f})"

    def summary(self) -> str:
        return (f"Day P&L: Rs {self.realized_pnl:.2f} | Trades: {self.trades_today} | "
                f"Kill: {'ON' if self.kill_on() else 'OFF'} | "
                f"DayStop: {'YES-' + self.stop_reason if self.stopped_for_day else 'no'}")
