"""Mobile remote: /commands + plain-English AI chat + Approve buttons.
ONLY your chat id can control. Long AI answers auto-split into parts.

The / list in Telegram is NOT from CommandHandler — it only appears after
setMyCommands succeeds (Bot API). We publish that list over HTTPS at start.
"""
import asyncio
import html as _html
import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request

log = logging.getLogger("telegram")

TG_LIMIT = 3500

# Telegram allows ONLY ONE getUpdates poller per bot token. If your laptop bot
# and the Render bot run together, Telegram kills one with HTTP 409 Conflict.
CONFLICT_MSG = ("TWO BOTS on ONE token: another instance is already polling with "
                "this TELEGRAM_BOT_TOKEN (your laptop / another server / the old "
                "deploy still shutting down). Stop the other one - only ONE bot can "
                "listen. Until then messages are split or missed.")


def _is_conflict(exc) -> bool:
    try:
        from telegram.error import Conflict
        if isinstance(exc, Conflict):
            return True
    except Exception:
        pass
    low = str(exc).lower()
    return "conflict" in low and ("getupdates" in low or "other bot instance" in low)


def _drop_pending() -> bool:
    """After a restart Telegram replays queued messages. For a TRADING bot, a
    30-minute-old 'buy 5 reliance' firing late is dangerous - so drop them.
    Set TG_DROP_PENDING=false if you want the backlog replayed instead."""
    return os.getenv("TG_DROP_PENDING", "true").strip().lower() in ("1", "true", "yes", "y")

# Shown when the user types /  (1–32 chars [a-z0-9_], no spaces).
# Plain name = equity. *_commodity / *_currency / *_crypto = that book only.
BOT_CMDS = [
    ("help", "Full command list"),
    ("status", "Bot + Kotak status"),
    ("update", "Live books snapshot, not Gemini"),
    ("pnl", "Equity P&L"),
    ("portfolio", "Equity portfolio"),
    ("portfolio_commodity", "Commodity paper portfolio"),
    ("positions", "Equity positions"),
    ("positions_commodity", "Commodity paper positions"),
    ("scan", "NSE equity Sid scan"),
    ("scan_sid", "Sid 44-MA Nifty scan"),
    ("scan_commodity", "GOLD SILVER CRUDE crypto paper"),
    ("scan_currency", "USDINR EURINR GBPINR"),
    ("scan_crypto", "BTC ETH paper"),
    ("tasks", "Equity tasks"),
    ("tasks_commodity", "Commodity paper tasks"),
    ("accuracy", "Equity swing accuracy"),
    ("buy", "Buy RELIANCE 5 or GOLD 1"),
    ("sell", "Sell equity or GOLD"),
    ("stop", "Stop new equity trades"),
    ("resume", "Resume equity entries"),
    ("squareoff", "Square off ALL equity"),
    ("squareoff_commodity", "Square off commodity paper"),
    ("sl", "Update equity SL: sl SBIN 985"),
]


def _split(text: str, lim: int = TG_LIMIT) -> list:
    """Split long text on newlines so nothing gets cut.

    Telegram is sent as PLAIN text (no parse_mode), so any HTML entity that
    slipped into a string ("P&amp;L", "&lt;") would be visible to the user as
    literal characters. Unescape here so every send path is clean.
    """
    text = _html.unescape(text or "")
    if len(text) <= lim:
        return [text]
    parts, cur = [], ""
    for line in text.split("\n"):
        if len(cur) + len(line) + 1 > lim:
            parts.append(cur)
            cur = line
        else:
            cur = cur + ("\n" if cur else "") + line
    if cur:
        parts.append(cur)
    return parts or [text]


def _tg_post(token: str, method: str, payload: dict, timeout: int = 20) -> dict:
    url = f"https://api.telegram.org/bot{token}/{method}"
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def publish_bot_commands(token: str, chat_id: str = "") -> str:
    """Push the / menu to Telegram. Independent of python-telegram-bot."""
    if not token or "PASTE" in token:
        return "skip"
    cmds = [{"command": c, "description": d} for c, d in BOT_CMDS]
    scopes = [{"type": "default"}, {"type": "all_private_chats"}]
    cid = None
    try:
        if chat_id and str(chat_id).lstrip("-").isdigit():
            cid = int(chat_id)
            scopes.append({"type": "chat", "chat_id": cid})
    except Exception:
        cid = None
    try:
        for sc in scopes:
            j = _tg_post(token, "setMyCommands", {"commands": cmds, "scope": sc})
            if not j.get("ok"):
                log.warning("setMyCommands %s: %s", sc.get("type"), j)
        _tg_post(token, "setChatMenuButton",
                 {"menu_button": {"type": "commands"}})
        if cid is not None:
            _tg_post(token, "setChatMenuButton",
                     {"chat_id": cid, "menu_button": {"type": "commands"}})
        j = _tg_post(token, "getMyCommands", {"scope": {"type": "default"}})
        n = len(j.get("result") or [])
        log.info("Telegram / menu published: %s commands", n)
        return f"ok {n}"
    except Exception as e:
        log.warning("publish_bot_commands failed: %s", e)
        return f"fail {e}"


def send_msg_sync(token: str, chat_id: str, text: str):
    if not token or "PASTE" in token or not chat_id:
        return
    try:
        from telegram import Bot

        async def _go():
            async with Bot(token) as b:
                parts = _split(text)
                for i, part in enumerate(parts):
                    head = f"(part {i+1})\n" if i else ""
                    part = _html.unescape(part)      # never ship "&amp;" to Telegram
                    # Ground truth: the log now shows the EXACT bytes handed to
                    # Telegram, so "what did the phone actually receive" is
                    # never a guessing game again.
                    log.info("TG SEND %d/%d %r", i + 1, len(parts), part[:70])
                    await b.send_message(chat_id=int(chat_id), text=head + part)

        asyncio.run(_go())
    except Exception as e:
        log.warning("telegram send failed: %s", e)


def send_buttons_sync(token: str, chat_id: str, text: str, pid: int):
    """Approval buttons for live AI trades."""
    try:
        from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup

        async def _go():
            async with Bot(token) as b:
                kb = InlineKeyboardMarkup([[
                    InlineKeyboardButton("✅ Approve", callback_data=f"ap:{pid}"),
                    InlineKeyboardButton("❌ Reject", callback_data=f"rj:{pid}")]])
                await b.send_message(chat_id=int(chat_id), text=text[:1000],
                                     reply_markup=kb)

        asyncio.run(_go())
    except Exception as e:
        log.warning("telegram buttons failed: %s", e)


class TelegramRemote(threading.Thread):
    daemon = True

    def __init__(self, token: str, chat_id: str, app):
        super().__init__(name="telegram-polling")
        self.token = token
        self.chat_id = str(chat_id)
        self.app = app
        self.ready = threading.Event()
        self._stop = threading.Event()  # set by stop() -> ends the polling loop
        self.stopped = False            # True once shutdown has completed
        self._last_conflict_log = 0.0   # log a Conflict once per 5 min, not per poll
        # "" while healthy. Set when polling dies or the token/chat id is missing,
        # so the dashboard + /api/status can tell the TRUTH instead of showing
        # a green "connected" next to a dead bot.
        self.error = ""

    def stop(self, timeout: float = 12.0) -> bool:
        """Close Telegram polling and shut the asyncio application down.

        Without this the daemon thread keeps its own asyncio loop alive and
        KEEPS ANSWERING MESSAGES - so the dashboard says "Bot stopped" while
        Telegram still replies. Returns True once the thread has really exited.
        """
        already = self._stop.is_set()
        self._stop.set()
        if not already:
            log.info("Telegram remote: stop requested")
        if threading.current_thread() is not self and self.is_alive():
            self.join(timeout=timeout)
        if self.is_alive():
            self.error = ("stop requested but the polling thread did not exit "
                          "within %.0fs" % timeout)
            log.warning("%s", self.error)
            return False
        self.stopped = True
        self.error = ""
        return True

    def _allowed(self, update) -> bool:
        try:
            return str(update.effective_chat.id) == self.chat_id
        except Exception:
            return False

    async def _reply_long(self, message, text: str):
        parts = _split(text)
        for i, part in enumerate(parts):
            head = f"(part {i+1})\n" if i else ""
            await message.reply_text(head + part)

    @staticmethod
    def _is_slow(text: str) -> bool:
        low = (text or "").lower()
        if any(w in low for w in ("news", "research", "headline", "analyse",
                                   "analyze", "ask all", "deepthink", "find ",
                                   "tell me", "what is", "what's", "who is",
                                   "explain", "launch", "event", "weather",
                                   "wether", "forecast", "monthly")):
            return True
        if "scan" in low:
            return True
        if any(w in low for w in ("update", "refresh")) and not any(
                w in low for w in (" sl", "/sl", "t1", "t2", "stop loss")):
            return True
        return False

    def run(self):
        if not self.token or "PASTE" in self.token or not self.chat_id:
            self.error = ("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID missing in .env "
                          "(mobile remote OFF)")
            log.warning("Telegram not configured — mobile remote OFF")
            self.ready.set()
            return
        pub = publish_bot_commands(self.token, self.chat_id)
        log.info("command menu: %s", pub)
        try:
            from telegram import BotCommand, Update
            from telegram.ext import (Application, CallbackQueryHandler,
                                      ContextTypes, MessageHandler, filters)
            try:
                from telegram import MenuButtonCommands
            except ImportError:
                MenuButtonCommands = None
        except Exception as e:
            self.error = f"python-telegram-bot missing/broken: {e}"
            log.error("telegram lib missing? pip install python-telegram-bot : %s", e)
            self.ready.set()
            return

        app = self.app
        reply_long = self._reply_long

        async def guard(update: Update) -> bool:
            if not self._allowed(update):
                if update.message:
                    await update.message.reply_text("⛔ Not your bot.")
                elif update.callback_query:
                    await update.callback_query.answer("⛔ Not your bot.")
                return False
            return True

        # Telegram cannot CSS-blink. Alternate visible/invisible dots so "..." flashes.
        FRAMES = (
            "⏳ Thinking...",
            "⏳ Thinking   ",
            "⏳ Thinking...",
            "⏳ Thinking   ",
            "⏳ Working...",
            "⏳ Working   ",
            "⏳ Working...",
            "⏳ Working   ",
            "⏳ Finding...",
            "⏳ Finding   ",
            "⏳ Checking...",
            "⏳ Checking   ",
        )

        async def with_thinking(message, sync_fn):
            """Placeholder on the bot side; dots animate until the result replaces it.
            Telegram cannot blink text — this is the closest native effect."""
            try:
                sent = await message.reply_text("⏳ Thinking.")
            except Exception:
                sent = None
            stop = asyncio.Event()

            async def spin():
                i = 0
                bot = message.get_bot()
                chat_id = message.chat_id
                while not stop.is_set():
                    try:
                        await bot.send_chat_action(chat_id, "typing")
                    except Exception:
                        pass
                    if sent is not None:
                        try:
                            await sent.edit_text(FRAMES[i % len(FRAMES)])
                        except Exception:
                            pass
                    i += 1
                    try:
                        await asyncio.wait_for(stop.wait(), timeout=0.4)
                    except asyncio.TimeoutError:
                        continue
                    except Exception:
                        break

            task = asyncio.create_task(spin())
            try:
                text = await asyncio.to_thread(sync_fn)
            except Exception as e:
                log.exception("work failed")
                text = f"⚠️ Failed: {e}"
            stop.set()
            try:
                await asyncio.wait_for(task, timeout=2)
            except Exception:
                task.cancel()
            parts = _split(text or "(empty)")
            if sent is not None:
                try:
                    await sent.edit_text(parts[0][:4090])
                    for extra in parts[1:]:
                        await message.reply_text(extra)
                    return
                except Exception:
                    pass
            await reply_long(message, text)

        async def slash(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
            if not await guard(update):
                return
            raw = update.message.text or ""
            if TelegramRemote._is_slow(raw):
                await with_thinking(update.message, lambda: app.cmd_slash(raw))
            else:
                await reply_long(update.message, app.cmd_slash(raw))

        async def chat(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
            if not await guard(update):
                return
            raw = update.message.text or ""

            def work():
                fast = app.cmd_chat_route(raw)
                if fast is not None:
                    return fast
                return app.ai_handle(raw)

            if TelegramRemote._is_slow(raw):
                await with_thinking(update.message, work)
                return
            fast = app.cmd_chat_route(raw)
            if fast is not None:
                await reply_long(update.message, fast)
                return
            await with_thinking(update.message, lambda: app.ai_handle(raw))

        async def button(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
            q = update.callback_query
            if not await guard(update):
                return
            await q.answer()
            data = q.data or ""
            if data.startswith("ap:"):
                await q.edit_message_text("⏳ Approved, executing...")
                await q.message.reply_text(app.approve(int(data[3:])))
            elif data.startswith("rj:"):
                await q.edit_message_text("❌ Rejected. No trade done.")
                app.reject(int(data[3:]))

        async def post_init(application):
            try:
                cmds = [BotCommand(c, d) for c, d in BOT_CMDS]
                await application.bot.set_my_commands(cmds)
                if MenuButtonCommands is not None:
                    await application.bot.set_chat_menu_button(
                        menu_button=MenuButtonCommands())
                try:
                    await application.bot.set_chat_menu_button(
                        chat_id=int(self.chat_id),
                        menu_button=MenuButtonCommands())
                except Exception:
                    pass
                got = await application.bot.get_my_commands()
                log.info("PTB / menu: %s commands", len(got))
            except Exception as e:
                log.warning("PTB set_my_commands: %s", e)

        def poll_error(exc):
            """PTB calls this on a failed getUpdates. Without it every failure
            dumps a 20-line traceback into the Render log."""
            if _is_conflict(exc):
                self.error = CONFLICT_MSG
                if time.time() - self._last_conflict_log > 300:
                    self._last_conflict_log = time.time()
                    log.error("TELEGRAM CONFLICT: %s", CONFLICT_MSG)
                return
            if isinstance(exc, KeyboardInterrupt) or "Unauthorized" in str(exc):
                self.error = f"polling stopped: {str(exc)[:160]}"
                log.error("telegram polling stopped: %s", str(exc)[:200])
                return
            self.error = f"polling error: {str(exc)[:160]}"
            log.warning("telegram polling error (will retry): %s", str(exc)[:200])

        async def handler_error(application, context):
            exc = getattr(context, "error", None)
            log.error("telegram handler error: %s", str(exc)[:300])

        async def amain():
            app_tg = (Application.builder()
                      .token(self.token)
                      .post_init(post_init)
                      .build())
            app_tg.add_error_handler(handler_error)
            # Any /command (including /scan@BotName) → cmd_slash
            app_tg.add_handler(MessageHandler(filters.COMMAND, slash))
            app_tg.add_handler(CallbackQueryHandler(button))
            app_tg.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat))
            await app_tg.initialize()
            await app_tg.start()
            drop = _drop_pending()
            await app_tg.updater.start_polling(
                drop_pending_updates=drop,     # never fire stale orders late
                error_callback=poll_error,     # clean logs, no traceback spam
            )
            log.info("Telegram remote ON (drop_pending_updates=%s)", drop)
            self.ready.set()
            # Block until stop() is called. The old code was
            # `await asyncio.Event().wait()` - an infinite wait that NOTHING
            # could ever cancel, which is exactly why "Stop Bot" left Telegram
            # answering messages while the dashboard reported "stopped".
            while not self._stop.is_set():
                await asyncio.sleep(0.5)
            log.info("Telegram remote: closing polling...")
            try:
                if app_tg.updater is not None and app_tg.updater.running:
                    await app_tg.updater.stop()      # stop getUpdates first
            except Exception as e:
                log.warning("updater.stop failed: %s", e)
            try:
                await app_tg.stop()
            except Exception as e:
                log.warning("app.stop failed: %s", e)
            try:
                await app_tg.shutdown()
            except Exception as e:
                log.warning("app.shutdown failed: %s", e)
            self.stopped = True
            log.info("Telegram remote OFF - polling closed cleanly")

        try:
            asyncio.run(amain())
        except Exception as e:
            # Typical causes: bad token -> "Unauthorized"; HTTP 409 -> two bots
            # are polling with the same token; no outbound network.
            if _is_conflict(e):
                self.error = CONFLICT_MSG
                log.error("TELEGRAM CONFLICT: %s", CONFLICT_MSG)
                return
            self.error = f"polling stopped: {e}"
            log.error("telegram polling stopped: %s", e)
            try:
                self.app.alert(f"⚠️ Telegram remote died: {e}\n"
                               "Check TELEGRAM_BOT_TOKEN (and that the host can "
                               "reach api.telegram.org:443).")
            except Exception:
                pass
