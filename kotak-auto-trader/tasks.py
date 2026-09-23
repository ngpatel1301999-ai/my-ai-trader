"""TASKS: give an order while away -> bot executes automatically.

Kinds:  price_above | price_below | time_once | pnl_above
Actions: notify | buy | sell | squareoff_all
Example: "buy 5 RELIANCE if above 3050" -> price_above task with buy action.
Saved in tasks.json (survives restart).
"""
import json
import logging
import os
from datetime import datetime, timedelta

import paths

log = logging.getLogger("tasks")


def _weekdays_elapsed(start: str, now: datetime) -> int:
    """Inclusive working days (Mon-Fri) from start date until now.date()."""
    try:
        d0 = datetime.strptime(start[:10], "%Y-%m-%d").date()
    except Exception:
        return 0
    d1 = now.date() if hasattr(now, "date") else now
    if d1 <= d0:
        return 0
    n, cur = 0, d0
    while cur < d1:
        cur += timedelta(days=1)
        if cur.weekday() < 5:
            n += 1
    return n
TASKS_FILE = "tasks.json"


class TaskEngine:
    def __init__(self, path: str = TASKS_FILE):
        # a bare file name ("tasks.json") goes to the state dir; an absolute
        # path is used as-is. Keeps old callers working.
        p = path or TASKS_FILE
        self.path = p if os.path.isabs(p) else paths.data_path(p)
        self.tasks = []
        self._next_id = 1
        self.load()

    def load(self):
        try:
            if os.path.exists(self.path):
                with open(self.path) as f:
                    d = json.load(f) or {}
                self.tasks = d.get("tasks", [])
                self._next_id = d.get("next_id", len(self.tasks) + 1)
        except Exception as e:
            log.warning("tasks load failed: %s", e)

    def save(self):
        try:
            with open(self.path, "w") as f:
                json.dump({"next_id": self._next_id, "tasks": self.tasks}, f, indent=1)
        except Exception as e:
            log.warning("tasks save failed: %s", e)

    def add(self, kind, action, symbol="", level=0.0, qty=0, note="", expires="",
            at_time="", exclusive=False, cancel_on_done=None, from_date="") -> int:
        try:
            q = float(qty or 0)
        except (TypeError, ValueError):
            q = 0.0
        if q == int(q):
            q = int(q)
        t = {"id": self._next_id, "kind": kind, "action": action,
             "symbol": symbol.upper(), "level": float(level or 0), "qty": q,
             "note": note, "expires": expires, "at_time": at_time,
             "exclusive": bool(exclusive),
             "cancel_on_done": list(cancel_on_done or []),
             "from_date": (from_date or "")[:10],
             "status": "open", "created": datetime.now().strftime("%Y-%m-%d %H:%M"),
             "result": ""}
        self._next_id += 1
        self.tasks.append(t)
        self.save()
        return t["id"]

    def open_tasks(self):
        return [t for t in self.tasks if t["status"] == "open"]

    def cancel(self, tid: int) -> bool:
        for t in self.tasks:
            if t["id"] == tid and t["status"] == "open":
                t["status"] = "cancelled"
                self.save()
                return True
        return False

    def mark_done(self, tid: int, result: str):
        for t in self.tasks:
            if t["id"] == tid:
                t["status"] = "done"
                t["result"] = result[:200]
        self.save()

    def mark_expired(self, tid: int):
        for t in self.tasks:
            if t["id"] == tid:
                t["status"] = "expired"
        self.save()

    def describe(self, t: dict) -> str:
        if t["kind"] == "pnl_above":
            return (f"#{t['id']} IF open swing profit >= Rs {t['level']:.0f} "
                    f"THEN {t['action']}")
        if t["kind"] == "pnl_below":
            return (f"#{t['id']} IF open swing LOSS >= Rs {t['level']:.0f} "
                    f"(P&L <= -{t['level']:.0f}) THEN {t['action']}")
        if t["kind"] == "pnl_pct_above":
            return (f"#{t['id']} IF book profit at or above {t['level']:g}% THEN {t['action']}")
        if t["kind"] == "pnl_pct_below":
            return (f"#{t['id']} IF book loss at or above {t['level']:g}% THEN {t['action']}")
        if t["kind"] in ("price_above", "price_below"):
            word = "above" if t["kind"] == "price_above" else "below"
            return (f"#{t['id']} IF {t['symbol']} {word} {t['level']:.2f} "
                    f"THEN {t['action']}{(' x' + str(t['qty'])) if t['qty'] else ''} "
                    f"{t['note']}")
        return f"#{t['id']} AT {t['at_time']} THEN {t['action']} {t['note']}"

    def check(self, prices: dict, now: datetime, extra=None):
        """prices: {TRADING_SYMBOL or SHORT: ltp}. Returns due open tasks."""
        extra = extra or {}
        due = []
        today = now.strftime("%Y-%m-%d")
        hm = now.strftime("%Y-%m-%d %H:%M")
        for t in self.open_tasks():
            if t.get("expires") and today > t["expires"]:
                self.mark_expired(t["id"])
                continue
            if t["kind"] == "time_once" and t.get("at_time") and hm >= t["at_time"]:
                due.append(t)
            elif t["kind"] == "pnl_above":
                if extra.get("unreal", 0) >= t["level"]:
                    due.append(t)
            elif t["kind"] == "pnl_below":
                if extra.get("unreal", 0) <= -abs(t["level"]):
                    due.append(t)
            elif t["kind"] in ("pnl_pct_above", "pnl_pct_below"):
                inv = extra.get("invested", 0) or 0
                unreal = extra.get("unreal", 0) or 0
                pct = (100.0 * unreal / inv) if inv > 0 else 0.0
                if t["kind"] == "pnl_pct_above" and pct >= t["level"]:
                    due.append(t)
                elif t["kind"] == "pnl_pct_below" and pct <= -abs(t["level"]):
                    due.append(t)
            elif t["kind"] == "working_days":
                start = (t.get("from_date") or t.get("created") or "")[:10]
                if start and _weekdays_elapsed(start, now) >= int(t["level"] or 0):
                    due.append(t)
            elif t["kind"] in ("price_above", "price_below"):
                px = prices.get(t["symbol"]) or prices.get(t["symbol"] + "-EQ")
                if not px:
                    continue
                if t["kind"] == "price_above" and px >= t["level"]:
                    due.append(t)
                elif t["kind"] == "price_below" and px <= t["level"]:
                    due.append(t)
        return due
