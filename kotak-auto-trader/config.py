"""All settings come from the .env file. No secrets are written in code."""
import os
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()


def _str(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _str_any(*names, default: str = "") -> str:
    """First non-empty env var wins (supports NEO_* and legacy KOTAK_* names)."""
    for n in names:
        v = os.getenv(n, "").strip()
        if v:
            return v
    return default


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def _bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "y")


@dataclass
class Settings:
    # ---- mode: swing | intraday | both ----
    bot_mode: str = _str("BOT_MODE", "swing").lower()
    trading_mode: str = _str("TRADING_MODE", "paper").lower()   # paper | live
    enable_live_orders: bool = _bool("ENABLE_LIVE_ORDERS", False)

    # ---- kotak ----
    consumer_key: str = _str_any("NEO_CONSUMER_KEY", "KOTAK_CONSUMER_KEY")
    mobile_number: str = _str_any("NEO_MOBILE_NUMBER", "KOTAK_MOBILE", "KOTAK_MOBILE_NUMBER")
    ucc: str = _str_any("NEO_UCC", "KOTAK_UCC")
    mpin: str = _str_any("NEO_MPIN", "KOTAK_MPIN")
    totp_secret: str = _str_any("NEO_TOTP_SECRET", "KOTAK_TOTP_SECRET")

    # ---- telegram ----
    tg_token: str = _str("TELEGRAM_BOT_TOKEN")
    tg_chat_id: str = _str("TELEGRAM_CHAT_ID")

    # ---- AI brain (Gemini FREE tier key from aistudio.google.com) ----
    gemini_key: str = _str("GEMINI_API_KEY")
    gemini_model: str = _str("GEMINI_MODEL", "gemini-2.5-flash")

    # ---- AI PERMISSIONS (you are the boss; AI cannot change these) ----
    ai_paper_trading: bool = _bool("AI_PAPER_TRADING", True)     # AI may trade fake money
    ai_trading_enabled: bool = _bool("AI_TRADING_ENABLED", False)  # AI may touch REAL money
    ai_require_approval: bool = _bool("AI_REQUIRE_APPROVAL", True)  # live trades need your tap
    ai_max_order_value_rs: float = _float("AI_MAX_ORDER_VALUE_RS", 10000)

    # ---- universe: plain names! tokens auto-found. e.g. RELIANCE,INFY,TCS ----
    watchlist_raw: str = _str("WATCHLIST", "RELIANCE,INFY,TCS,HDFCBANK")
    exchange_segment: str = "nse_cm"

    # ---- intraday ORB settings ----
    qty_per_trade: int = _int("QTY_PER_TRADE", 1)
    max_daily_loss_rs: float = _float("MAX_DAILY_LOSS_RS", 2000)
    max_trades_per_day: int = _int("MAX_TRADES_PER_DAY", 4)
    target_r_multiple: float = _float("TARGET_R_MULTIPLE", 1.5)
    product_intraday: str = _str("PRODUCT", "MIS")
    poll_seconds: int = _int("POLL_SECONDS", 5)

    # ---- swing settings ----
    swing_strategy: str = _str("SWING_STRATEGY", "sid44").lower()  # sid44 | classic
    swing_sl_pct: float = _float("SWING_SL_PCT", 2.0)
    swing_t1_pct: float = _float("SWING_T1_PCT", 5.0)
    swing_t2_pct: float = _float("SWING_T2_PCT", 8.0)
    max_hold_days: int = _int("MAX_HOLD_DAYS", 10)          # ~2 weeks
    max_swing_positions: int = _int("MAX_SWING_POSITIONS", 3)
    max_new_per_day: int = _int("MAX_NEW_PER_DAY", 2)
    swing_min_score: int = _int("SWING_MIN_SCORE", 70)
    swing_auto_buy: bool = _bool("SWING_AUTO_BUY", False)  # EOD scan must NOT auto-buy unless true
    risk_per_trade_rs: float = _float("RISK_PER_TRADE_RS", 1000)
    max_position_value_rs: float = _float("MAX_POSITION_VALUE_RS", 30000)
    scan_time: str = _str("SCAN_TIME", "15:20")
    guardian_seconds: int = _int("GUARDIAN_SECONDS", 60)

    # ---- market times (IST) ----
    login_time: str = "08:45"
    market_open: str = "09:15"
    range_end: str = "09:30"
    entries_stop: str = "14:30"
    square_off: str = "15:15"
    hard_stop: str = "15:30"

    candle_minutes: int = 5
    watchlist: list = field(default_factory=list)

    def __post_init__(self):
        self.watchlist = []
        for item in self.watchlist_raw.split(","):
            item = item.strip().upper()
            if not item:
                continue
            if ":" in item:  # legacy fixed form RELIANCE-EQ:2885
                sym, tok = item.split(":", 1)
                self.watchlist.append({"symbol": sym.strip(), "token": tok.strip(),
                                       "trading": sym.strip()})
            else:  # plain name -> token auto-found at startup
                short = item[:-3] if item.endswith("-EQ") else item
                self.watchlist.append({"symbol": short, "token": "", "trading": ""})

    @property
    def is_live(self) -> bool:
        return self.trading_mode == "live" and self.enable_live_orders

    @property
    def swing_on(self) -> bool:
        return self.bot_mode in ("swing", "both")

    @property
    def intraday_on(self) -> bool:
        return self.bot_mode in ("intraday", "both")

    def ai_may_trade(self) -> tuple:
        """(allowed, why). AI can NEVER change this itself."""
        if self.is_live:
            if not self.ai_trading_enabled:
                return False, "AI live trading is OFF (AI_TRADING_ENABLED=false in .env)"
            return True, "live-ok"
        if not self.ai_paper_trading:
            return False, "AI paper trading is OFF"
        return True, "paper-ok"

    def validate(self) -> list:
        problems = []
        if not self.consumer_key or "PASTE" in self.consumer_key:
            problems.append("NEO_CONSUMER_KEY missing in .env")
        if not self.mobile_number or "X" in self.mobile_number:
            problems.append("NEO_MOBILE_NUMBER missing in .env")
        if not self.ucc or "YOUR" in self.ucc:
            problems.append("NEO_UCC missing in .env")
        if not self.mpin:
            problems.append("NEO_MPIN missing in .env")
        if not self.totp_secret or "PASTE" in self.totp_secret:
            problems.append("NEO_TOTP_SECRET missing in .env (needed for auto-login)")
        if not self.watchlist:
            problems.append("WATCHLIST empty in .env")
        if not self.tg_token or "PASTE" in self.tg_token:
            problems.append("TELEGRAM_BOT_TOKEN missing (mobile remote will not work)")
        if not self.tg_chat_id or "PASTE" in self.tg_chat_id:
            problems.append("TELEGRAM_CHAT_ID missing (mobile remote will not work)")
        return problems

    def warnings(self) -> list:
        w = []
        if not self.gemini_key or "PASTE" in self.gemini_key:
            w.append("No GEMINI_API_KEY -> AI speaks basic mode only (still works). Free key: aistudio.google.com")
        return w


SETTINGS = Settings()
