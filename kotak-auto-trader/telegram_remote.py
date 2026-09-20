"""Mobile remote: /commands + plain-English AI chat + Approve buttons.
ONLY your chat id can control. Long AI answers auto-split into parts.

The / list in Telegram is NOT from CommandHandler — it only appears after
setMyCommands succeeds (Bot API). We publish that list over HTTPS at start.
"""
import asyncio
import json
import logging
import threading
import urllib.error
import urllib.request

log = logging.getLogger("telegram")

TG_LIMIT = 3500

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
    """Split long text on newlines so nothing gets cut."""
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
                for i, part in enumerate(_split(text)):
                    head = f"(part {i+1})\n" if i else ""
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
                                   "explain", "launch", "event")):
            return True
        if "scan" in low:
            return True
        if any(w in low for w in ("update", "refresh")) and not any(
                w in low for w in (" sl", "/sl", "t1", "t2", "stop loss")):
            return True
        return False

    def run(self):
        if not self.token or "PASTE" in self.token or not self.chat_id:
            log.warning("Telegram not configured — mobile remote OFF")
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
            log.error("telegram lib missing? pip install python-telegram-bot : %s", e)
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

        async def amain():
            app_tg = (Application.builder()
                      .token(self.token)
                      .post_init(post_init)
                      .build())
            # Any /command (including /scan@BotName) → cmd_slash
            app_tg.add_handler(MessageHandler(filters.COMMAND, slash))
            app_tg.add_handler(CallbackQueryHandler(button))
            app_tg.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat))
            await app_tg.initialize()
            await app_tg.start()
            await app_tg.updater.start_polling()
            log.info("Telegram remote ON")
            await asyncio.Event().wait()

        try:
            asyncio.run(amain())
        except Exception as e:
            log.error("telegram polling stopped: %s", e)
