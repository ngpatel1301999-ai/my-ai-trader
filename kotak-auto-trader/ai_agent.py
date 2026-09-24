"""Agent: trading commands skip the LLM. Anything else = live facts, not a swing brief.

AGENT_BUILD must match MAIN_BUILD on Telegram start. If it does not, you
copied the wrong files.
"""
import logging
import re

import ai_router
import universe
import web_tools
from memory import Memory, Profile

log = logging.getLogger("ai")
try:
    from build_stamp import BUILD as AGENT_BUILD
except ImportError:
    AGENT_BUILD = "MISSING-build_stamp.py"

SYSTEM = """You are the user's personal trading assistant inside THEIR OWN Kotak Neo bot.
Answer like a world-class AI assistant: warm, clear, structured. SIMPLE words.
TOOLS: status, pnl, positions, accuracy, scan, help, quote{symbol},
buy{symbol,qty?}, sell{symbol,qty?}, squareoff{symbol|ALL},
task_create{kind,symbol,level,action,qty?,note?}, task_list, task_cancel{id}
PROTOCOL - reply ONLY JSON:
{"thinking":"1-line","reply":"message","actions":[{"tool":"..","args":{}}],"done":true,"need_user":""}
Rules: "buy X if above Y"/"alert me" -> task_create, never an immediate trade.
qty missing? omit qty. done=true when complete.
"""

GENERAL_WRITE = """You are a sharp Telegram assistant in India (Gemini-quality, not a lecture).

LENGTH is given below. Obey it strictly.
- SHORT: 4-8 lines total. First sentence = the answer. Then 2-4 bullets. Stop. No essay.
- DETAIL: complete but still tight. First sentence = the answer. Then a short table/bullets of the facts. One ⚠️ if needed. Still under ~20 lines. No textbook.

PLAIN TEXT. No markdown ** ##. No URLs. No Want (a)(b) unless they asked about a stock trade.
Use ONLY FACTS. Do not invent numbers. Ignore stale 2025 / wrong-topic items.
Today-question = today. Monthly-question = rest of this month.
No swing, Sid 44, or NSE scan unless they asked about a stock.
If they ask which insurance/mediclaim is best: 2-3 well-known plan types in their budget, plus ⚠️ not personal advice — compare on the insurer site / IRDAI. Never pick one policy as the only winner.
Match English / Hindi / Hinglish.
"""

WRITEUP = """You are a personal NSE/BSE swing-trading assistant on Telegram, talking to one user in India.
Write the way a world-class assistant writes: warm, direct, specific, honest.

FORMAT (must follow, PLAIN TEXT — no markdown, no asterisks, no hash headings):
1) Direct answer FIRST, 1-2 lines, with an emoji. If they asked about a stock: Neutral / Cautiously bullish / Cautiously bearish for a 1-2 week SWING, and WHY in one clause.
2) Then 3-6 short bullets: what it is, last price if given, what the last few days' news actually says. Paraphrase headlines. Do NOT paste raw URLs.
3) One risk line starting with ⚠️. Never promise profit. Not SEBI-registered advice. Paper money until they say otherwise.
4) End with exactly: Want: (a) ... (b) ... ?

ONLY use the FACTS below. If a number is missing, say so. If headlines are unrelated (submarine, random labs), ignore them and say news was noisy.

HARD FACT RULES (breaking one of these is worse than saying "I don't know"):
- NEVER invent a P/E, a "technical rating", a target price, a broker recommendation or a percentage that is not literally in FACTS.
- If FACTS has LIVE_LTP, that is THE price. Never quote a price that appears inside a headline - headlines carry old prices.
- Headlines are dated. Anything older than 30 days is OLD news: say "announced back in <month>, not new". NEVER call it "recent" or "latest".
- If several deals were announced together, mention all of them - do not report only one.
- The swing verdict MUST agree with TECHNICALS: price BELOW the 50DMA and 200DMA = Cautiously bearish, whatever the headlines sound like. Never call a stock in a downtrend a technical buy.
- If TECHNICALS are missing, say so; do not guess them.
NEVER claim you updated SL, bought, sold, or cancelled a task. Those need a real tool. If they asked to change SL, say: type /sl SBIN 985
Match the user's language (English / Hindi / Hinglish).
"""

SELF_TOOLS = {"web_search", "web_read", "deepthink", "update_models", "update_self"}

FAST_EXACT = {
    "status", "my status",
    "position", "positions", "my position", "my positions",
    "pnl", "profit", "p&l", "p/l",
    "portfolio", "my portfolio", "current pnl",
    "help",
    "task", "tasks", "my task", "my tasks",
    "accuracy", "win rate", "winrate",
}


IDENTITY = (
    "I'm your personal Telegram bot. You built me for paper trading + Q&A. "
    "I have no age and no Google boss. Google Gemini, news and weather are tools I call. "
    "They did not create me — you did."
)

GREET = re.compile(
    r"^\s*(hi|hii|hiii|hey|hello|yo|namaste|namaskar|hola|sup|good morning|"
    r"good evening|good afternoon|ok|okay|thanks|thank you|thx)\s*[!.]*\s*$",
    re.I)

WHOAMI = re.compile(
    r"who are you|what(?:'s| is) your name|your age|how old are you|"
    r"who (?:is|are) your boss|who (?:made|created|built) you|"
    r"who is your (?:creator|owner|father)|are you google|"
    r"you(?:re|'re|r) name|you(?:re|'re|r) age",
    re.I)


def tg_plain(s: str) -> str:
    s = (s or "").replace("**", "").replace("__", "")
    s = re.sub(r"^#+\s*", "", s, flags=re.M)
    s = re.sub(r"`+", "", s)
    return s.strip()


class Agent:
    def __init__(self):
        self.mem = Memory()
        self.prof = Profile()
        # main.py injects this: callable(symbol) -> {"ltp": float, "src": str}.
        # Gives research answers the LIVE Kotak price instead of a number the AI
        # copied out of a headline.
        self.quote_hook = None

    def handle(self, text: str, context: str, executor) -> str:
        text = (text or "").strip()
        if not text:
            return "Say something 🙂"
        low = text.lower()
        if low in ("forget", "clear memory", "reset memory", "forget everything"):
            self.mem.clear()
            return "🧠 Memory cleared. Fresh start!"
        m = re.match(r"remember (that )?(.+)", text, re.I)
        if m:
            self.prof.add_note(m.group(2).strip())
            return f"✍️ Noted: {m.group(2).strip()[:120]}"

        if GREET.match(text):
            out = "Hi. I'm your paper-trading Telegram bot — you built me. Ask anything."
            self.mem.add("user", text)
            self.mem.add("assistant", out)
            return out
        if WHOAMI.search(low) or re.search(
                r"\b(i created you|i made you|my contribution|not google)\b", low):
            out = IDENTITY
            if re.search(r"\bgoogle\b|other tools|contribution", low):
                out += (" Tools I use when needed: Gemini, news feeds, weather. "
                        "That is help, not ownership.")
            self.mem.add("user", text)
            self.mem.add("assistant", out)
            return out

        if self._is_modify(low):
            return self._modify_pos(text, executor)
        if low.startswith("update your") or "update all ai" in low or "update model" in low:
            return tg_plain(ai_router.auto_update_all())
        if "update yourself" in low:
            return ai_router.do_self_update()
        if "refresh universe" in low or "update universe" in low:
            return universe.refresh_from_nse()
        if low.startswith("find ") or low.startswith("search stock"):
            return self._find(text)
        if low == "scan" or low.startswith("scan "):
            if re.search(r"\bcommodit|\b(mcx|comex)\b|\bcrypto|\b(currency|currencies|forex)\b", low):
                return ("That's not an NSE Sid scan.\n"
                        "Type: scan commodity | scan currency | scan crypto")
            return self._scan(text)
        if self._is_fast(low):
            return self._offline(text, executor, silent=True)
        if re.search(r"\b(buy|sell|alert|notify|square\s*off|squareoff)\b", low):
            return self._json_tools(text, context, executor)

        # Named NSE research ONLY when they clearly asked about a stock.
        if self._is_market_wide(low):
            return self._market_news(text)
        if (self._looks_like_stock_q(low) and self._pick_symbol(text)
                and any(w in low for w in ("research", "analyse", "analyze",
                                           "news", "headline", "why is",
                                           "what happened", "swing"))):
            return self._research(text, context)
        # Plain ticker alone or "RELIANCE price" / "hero moto" -> Kotak Neo preferred (user demanded)
        # User said: any share name or price query should use Kotak, not Google
        sym_plain = self._pick_symbol(text)
        if sym_plain and sym_plain not in web_tools._SKIP_TICKER:
            # short query (1-4 words) that looks like just a stock + optional price words
            if len(text.split()) <= 4 and (
                low.strip() == sym_plain.lower()
                or low.strip() in (sym_plain.lower() + " price", sym_plain.lower() + " share price", "price of " + sym_plain.lower(), sym_plain.lower() + " ltp", sym_plain.lower() + " cmp")
                or re.search(r"\b(price|ltp|cmp|rate|value|share price|stock price)\b", low)
                or len(text.split()) <= 2
            ):
                return self._research(text, context)
            # also if text is just 1-2 words and contains a valid NSE ticker, research it
            if len(text.split()) <= 2 and sym_plain:
                return self._research(text, context)

        # Default: Google / Redmi / any topic = live facts. Never WRITEUP.
        return self._general(text)

    def _is_modify(self, low: str) -> bool:
        if not re.search(r"\b(sl|stop[\s-]?loss|t1|t2|target)\b", low):
            return False
        return bool(re.search(r"\b(update|set|change|move|trail|modify|put)\b", low))

    def _modify_pos(self, text: str, executor) -> str:
        low = text.lower()
        sl = t1 = t2 = None
        nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", text)]
        nums = [n for n in nums if 5 < n < 1_000_000]
        level = nums[-1] if nums else None
        if level is None:
            return "Need a price. Example: Update SL 985 of SBIN"
        if re.search(r"\b(t1|target\s*1)\b", low):
            t1 = level
        elif re.search(r"\b(t2|target\s*2)\b", low):
            t2 = level
        else:
            sl = level
        sym = self._pick_symbol(text)
        if not sym:
            return "Which stock? Example: Update SL 985 of SBIN"
        out = executor("modify_levels", {"symbol": sym, "sl": sl, "t1": t1, "t2": t2})
        self.mem.add("user", text)
        self.mem.add("assistant", out)
        return out

    def _is_fast(self, low: str) -> bool:
        s = low.strip(" ?!.")
        if s in FAST_EXACT:
            return True
        if re.match(r"cancel task #?\d+$", s):
            return True
        if (("square off" in s or s in ("squareoff", "close all"))
                and "if " not in s and "when " not in s):
            return True
        return False

    def _watchlist(self) -> list:
        try:
            from config import SETTINGS as _S
            return [w["symbol"] for w in _S.watchlist if w.get("symbol")]
        except Exception:
            return ["RELIANCE", "INFY", "TCS", "HDFCBANK", "SBIN", "ICICIBANK", "LT"]

    def _scan(self, text: str) -> str:
        try:
            label, syms = universe.resolve_scan(text, self._watchlist())
            if not syms:
                return "Nothing to scan. Try: scan nifty50 | scan bank | find jewellery"
            rows = universe.scan_scores(syms)
            return universe.format_scan(label, rows)
        except Exception as e:
            log.exception("scan failed")
            return f"Scan failed: {e}\nWant: (a) scan nifty50 (b) /status ?"

    def _find(self, text: str) -> str:
        hits = universe.find(text, 15)
        if not hits:
            return ("No match in the directory yet. Try `refresh universe` "
                    "(downloads all NSE names on your Wi-Fi), or `find bank`.\n"
                    "Want: (a) scan nifty50 (b) refresh universe ?")
        lines = [f"Found {len(hits)}:"]
        for h in hits:
            lines.append(f"• {h.get('symbol')} — {h.get('name') or h.get('symbol')}")
        lines.append("Want: (a) research the first one (b) scan this list (c) add one to watchlist ?")
        return "\n".join(lines)

    def _pick_symbol(self, text: str) -> str:
        """Only real tickers. Never Google/Redmi/Pixel as NSE names."""
        sym = web_tools.extract_nse_symbol(text)
        if sym and sym not in web_tools._SKIP_TICKER:
            return sym
        if not self._looks_like_stock_q((text or "").lower()):
            return ""
        words = re.findall(r"[A-Za-z]+", text or "")
        if len(words) > 8:
            return ""
        hits = universe.find(text, 1)
        return hits[0]["symbol"] if hits else ""

    def _looks_like_stock_q(self, low: str) -> bool:
        return bool(re.search(
            r"\b(nse|bse|swing|kotak|sid|watchlist|equity|share price|"
            r"stock of|ltp|cmp|portfolio|square\s*off|nifty|sensex|"
            r"buy|sell|research|analyse|analyze)\b",
            low or ""))

    def _is_market_wide(self, low: str) -> bool:
        return bool(re.search(
            r"indian stock market|stock market (today|news|highlight)|"
            r"market highlight|today'?s (market|highlight)|"
            r"\bsensex\b|\bnifty\b|market today|markets today",
            low or ""))

    def _research(self, text: str, context: str) -> str:
        if self._is_market_wide((text or "").lower()):
            return self._market_news(text)
        sym = self._pick_symbol(text)
        if not sym:
            return self._general(text)
        facts = web_tools.nse_research(sym)
        if self.quote_hook:
            try:
                q = self.quote_hook(sym) or {}
                if q.get("ltp"):
                    facts["live_ltp"] = q["ltp"]
                    facts["ltp_src"] = q.get("src") or "kotak-live"
            except Exception as e:
                log.warning("live quote hook failed for %s: %s", sym, e)
        return self._write_trade(text, context, facts)

    def _wants_detail(self, text: str) -> bool:
        t = (text or "").lower()
        return bool(re.search(
            r"\b(detail|details|detailed|in detail|full detail|"
            r"explain fully|more info|elaborate|long answer)\b", t))

    def _general(self, text: str) -> str:
        """Short by default. Word 'detail' = longer. Never a lecture."""
        facts = web_tools.general_facts(text)
        detail = self._wants_detail(text)
        length = "DETAIL" if detail else "SHORT"
        if facts.get("intent") == "weather":
            out = self._weather_report(facts, detail=detail)
            self.mem.add("user", text)
            self.mem.add("assistant", out)
            return out
        raw = self._general_report(facts)
        facts_txt = self._facts_for_write(facts) or raw
        hist = self.mem.context_text() or "none"
        try:
            polished = ai_router.ask_text(
                f"LENGTH={length}\nUSER asked: {text}\n"
                f"RECENT CHAT (follow-ups use this):\n{hist[:1200]}\n\n"
                f"FACTS (do not invent):\n{facts_txt}\n\nFALLBACK:\n{raw[:800]}",
                GENERAL_WRITE)
        except Exception:
            polished = ""
        out = tg_plain(polished) if polished and len(polished) > 40 else raw
        if length == "SHORT" and out.count("\n") > 10:
            out = "\n".join(out.splitlines()[:8])
        out = re.sub(r"https?://\S+", "", out)
        self.mem.add("user", text)
        self.mem.add("assistant", out)
        return out

    def _facts_for_write(self, facts: dict) -> str:
        bits = [f"intent={facts.get('intent')} span={facts.get('span') or ''}"]
        now = facts.get("now") or {}
        if now.get("temp") is not None:
            bits.append(f"NOW {now.get('place')}: {now.get('temp')}C rh {now.get('rh')}")
        for d in facts.get("daily") or []:
            bits.append(
                f"DAY {d.get('date')} {d.get('tmin')}-{d.get('tmax')} "
                f"rain% {d.get('pop')}")
        if facts.get("wiki"):
            bits.append("WIKI: " + facts["wiki"][:400])
        for n in (facts.get("news") or [])[:5]:
            bits.append("• " + (n.get("title") or ""))
            if n.get("body"):
                bits.append("  " + n["body"][:220])
        return "\n".join(bits) if len(bits) > 1 else "(no facts fetched)"

    def _market_news(self, text: str) -> str:
        facts = web_tools.market_facts()
        out = self._market_report(facts)
        self.mem.add("user", text)
        self.mem.add("assistant", out)
        return out

    def _write_trade(self, text, context, facts, extra_note=""):
        facts_txt = self._facts_block(facts) if facts else "(no stock facts)"
        body = (f"USER asked: {text}\nBOT CONTEXT: {context}\n"
                f"{'OTHER AI VIEWS:' + extra_note if extra_note else ''}\n\nFACTS:\n{facts_txt}")
        writeup = ai_router.ask_text(body, WRITEUP)
        if writeup:
            out = tg_plain(writeup)
            out = re.sub(r"https?://\S+", "", out)
            self.mem.add("user", text)
            self.mem.add("assistant", out)
            return out
        if facts:
            out = self._facts_report(facts)
            self.mem.add("user", text)
            self.mem.add("assistant", out)
            return out
        return self._general(text)

    def _yesno_line(self, facts: dict) -> str:
        q = (facts.get("query") or "").lower()
        blob = " ".join(
            ((n.get("title") or "") + " " + (n.get("body") or ""))
            for n in (facts.get("news") or [])).lower()
        if ("nse ipo" in q or ("nse" in q and "ipo" in q)) and re.search(
                r"list", q):
            if re.search(r"list(?:s|ing)? on (the )?(rival )?bse|bse only|"
                         r"not (be )?listed on nse|cannot list on (its )?own",
                         blob):
                return ("No. NSE IPO lists on BSE, not on NSE. "
                        "SEBI does not allow an exchange to list on itself.")
            if "bse" in blob and "nse ipo" in blob:
                return ("No. Coverage says NSE IPO lists on BSE, not NSE.")
        if facts.get("wiki") and len(facts["wiki"]) > 40:
            return facts["wiki"].split(".")[0][:220] + "."
        if facts.get("news"):
            return web_tools.strip_urls(facts["news"][0].get("title") or "")[:200]
        return "I could not get a clear yes/no from live news just now."

    def _story_bullets(self, stories, n=4) -> list:
        lines = []
        for item in (stories or [])[:n]:
            title = web_tools.strip_urls(item.get("title") or "")
            body = web_tools.strip_urls(item.get("body") or "")
            if not title:
                continue
            lines.append(f"• {title}")
            if body and body.lower() not in title.lower():
                lines.append(f"  {body[:280]}")
        return lines

    def _weather_report(self, facts: dict, detail: bool = False) -> str:
        now = facts.get("now") or {}
        daily = facts.get("daily") or []
        place = now.get("place") or facts.get("place") or "Ahmedabad"
        if not daily and not now.get("temp"):
            return (f"Could not fetch the live forecast for {place} just now. "
                    "Try again in a minute.")
        wmo = getattr(web_tools, "_WMO", {})
        span = facts.get("span") or "week"
        if span == "today":
            lines = [f"{place} — today."]
        elif span == "month":
            lines = [f"{place} — rest of this month (live forecast)."]
        else:
            lines = [f"{place} — next {len(daily) or facts.get('days') or 5} days."]
        if now.get("temp") is not None:
            sky = wmo.get(int(now.get("code") or 0), "")
            lines.append(
                f"Now: {now['temp']:.0f}°C"
                + (f", {sky}" if sky else "")
                + (f", humidity {now['rh']:.0f}%" if now.get("rh") is not None else "")
                + (f", wind {now['wind']:.0f} km/h" if now.get("wind") is not None else "")
            )
        if span == "month" and not detail:
            pops = [d.get("pop") or 0 for d in daily]
            tmaxs = [d.get("tmax") for d in daily if d.get("tmax") is not None]
            tmins = [d.get("tmin") for d in daily if d.get("tmin") is not None]
            lines.append("")
            if pops:
                lines.append(f"Rain likelier early (~{max(pops):.0f}% peak), then mostly dry.")
            if tmins and tmaxs:
                lines.append(f"Range about {min(tmins):.0f}–{max(tmaxs):.0f}°C through month-end.")
            lines.append("Say monthly detail for each day.")
            return "\n".join(lines)
        lines.append("")
        show = daily[:1] if (span == "today" and not detail) else daily
        for d in show:
            try:
                from datetime import date as _date
                dt = _date.fromisoformat(str(d.get("date"))[:10])
                day = "Today" if dt == _date.today() else dt.strftime("%a %d %b")
            except Exception:
                day = str(d.get("date") or "")[:10]
            sky = wmo.get(int(d.get("code") or 0), "")
            tmax, tmin = d.get("tmax"), d.get("tmin")
            rain, pop = d.get("rain"), d.get("pop")
            bit = f"• {day}: "
            if tmin is not None and tmax is not None:
                bit += f"{tmin:.0f}–{tmax:.0f}°C"
            if sky:
                bit += f"  {sky}"
            if pop is not None:
                bit += f"  rain {pop:.0f}%"
            elif rain is not None:
                bit += f"  rain {rain:.1f} mm"
            lines.append(bit)
        if span == "today" and daily and (daily[0].get("pop") or 0) >= 40:
            lines.append("Carry a light rain jacket later today.")
        if span == "month":
            lines.append("True 30-day day-by-day is not published. This is the rest of this month from the live model.")
        lines.append("Live forecast — not old news pages.")
        return "\n".join(lines)

    def _general_report(self, facts: dict) -> str:
        intent = facts.get("intent") or "facts"
        stories = facts.get("news") or []
        wiki = facts.get("wiki") or ""
        lines = []
        if intent == "weather":
            return self._weather_report(facts)
        if intent == "yesno":
            lines.append(self._yesno_line(facts))
            extra = self._story_bullets(stories, 3)
            if extra:
                lines.append("")
                lines.extend(extra)
        elif intent in ("india_news", "news"):
            lines.append("Today:")
            lines.extend(self._story_bullets(stories, 6))
        elif wiki and not stories:
            lines.append(wiki[:700])
        else:
            if wiki:
                lines.append(wiki[:280])
                lines.append("")
            if stories:
                lines.extend(self._story_bullets(stories, 4))
        if not lines:
            return ("I couldn't fetch live facts for that just now. "
                    "Try again in a minute, or name it more simply.")
        return "\n".join(lines).strip()

    def _market_report(self, facts: dict) -> str:
        def one(name, last, prev):
            if last and prev:
                return f"{name} {last:.2f} ({100.0 * (last - prev) / prev:+.2f}%)"
            if last:
                return f"{name} {last:.2f}"
            return f"{name} ?"
        lines = [
            "Indian market snapshot:",
            "• " + one("Nifty", facts.get("nifty"), facts.get("nifty_prev")),
            "• " + one("Sensex", facts.get("sensex"), facts.get("sensex_prev")),
            "",
        ]
        for n in (facts.get("news") or [])[:6]:
            title = web_tools.strip_urls(n.get("title") or "")
            body = web_tools.strip_urls(n.get("body") or "")
            lines.append(f"• {title}")
            if body:
                lines.append(f"  {body[:240]}")
        lines.append("")
        lines.append("⚠️ Facts only — not a buy/sell call.")
        return "\n".join(lines)

    def _json_tools(self, text, context, executor) -> str:
        base = (f"CONTEXT: {context}\nPROFILE: {self.prof.context_text() or 'none'}\n"
                f"HISTORY:\n{self.mem.context_text() or 'none'}\nUSER: {text}")
        extra, reply_saved = "", ""
        for rnd in range(1, 3):
            out = ai_router.ask_json(SYSTEM, base + extra)
            if out is None:
                break
            actions = out.get("actions") or []
            reply_saved = out.get("reply", "") or reply_saved
            results = []
            for act in actions[:3]:
                tool = act.get("tool", "?")
                try:
                    if tool in SELF_TOOLS:
                        res = self._self_tool(tool, act.get("args") or {}, context)
                    else:
                        res = executor(tool, act.get("args") or {})
                    results.append(f"[{tool}] {res}")
                except Exception as e:
                    results.append(f"[{tool}] FAILED: {e}")
            if out.get("need_user"):
                final = tg_plain((reply_saved + "\n❓ " + out["need_user"]).strip())
                self.mem.add("user", text)
                self.mem.add("assistant", final)
                return final
            if out.get("done", True) or not actions or rnd == 2:
                final = tg_plain(self._combine(reply_saved, results))
                self.mem.add("user", text)
                self.mem.add("assistant", final)
                return final
            extra = "\nPREVIOUS ROUND RESULTS:\n" + "\n".join(results)
        return self._general(text)

    def _facts_block(self, facts: dict) -> str:
        last, prev = facts.get("last"), facts.get("prev")
        px = f"yahoo_last={last}" if last else "yahoo_last=unknown"
        if prev:
            px += f" prev_close={prev}"
        if facts.get("live_ltp"):
            px = (f"LIVE_LTP={facts['live_ltp']} "
                  f"(source={facts.get('ltp_src', 'kotak-live')}, USE THIS PRICE) | " + px)
        lines = [f"SYMBOL: {facts['symbol']}", f"COMPANY: {facts['name']}",
                 f"PRICE: {px}"]
        t = facts.get("tech") or {}
        if t:
            bits = []
            if t.get("sma50"):
                bits.append(f"50DMA={t['sma50']} (price {t.get('vs_sma50', '?')})")
            if t.get("sma200"):
                bits.append(f"200DMA={t['sma200']} (price {t.get('vs_sma200', '?')}"
                            f", {t.get('off_sma200_pct', '?')}% away)")
            if t.get("hi52"):
                bits.append(f"52wk_range={t['lo52']}-{t['hi52']}"
                            f" ({t.get('off_hi52_pct', '?')}% off the high)")
            if t.get("ret_1y_pct") is not None:
                bits.append(f"1yr_return={t['ret_1y_pct']}%")
            if bits:
                lines.append("TECHNICALS (measured, NOT a rating - never invent one): "
                             + " | ".join(bits))
        lines.append("HEADLINES (each dated; TODAY is the reference):")
        for i, n in enumerate(facts.get("news") or [], 1):
            title = web_tools.strip_urls(n.get("title") or "")
            body = web_tools.strip_urls(n.get("body") or "")
            d = n.get("date") or "date-unknown"
            age = n.get("age_days")
            tag = f"[{d}]" if age is None else f"[{d} = {age:.0f} day(s) old]"
            if n.get("old"):
                tag += " <-- STALE: call it OLD news, never 'recent'"
            lines.append(f"  {i}. {tag} {title}")
            if body:
                lines.append(f"     {body[:240]}")
        if not facts.get("news"):
            lines.append("  (none)")
        return "\n".join(lines)

    def _facts_report(self, facts: dict) -> str:
        sym = facts["symbol"]
        last, prev = facts.get("last"), facts.get("prev")
        if last and prev:
            chg = last - prev
            pct = (chg / prev * 100) if prev else 0
            px = f"Rs {last:.2f}  ({chg:+.2f}, {pct:+.1f}% vs prev close Rs {prev:.2f})"
        elif last:
            px = f"Rs {last:.2f}"
        else:
            px = "not available right now"
        bullets = []
        for n in (facts.get("news") or [])[:4]:
            title = web_tools.strip_urls(n.get("title") or "")
            body = web_tools.strip_urls(n.get("body") or "")
            bullets.append(f"• {title}")
            if body and body.lower() not in title.lower():
                bullets.append(f"  {body[:240]}")
        news = "\n".join(bullets) if bullets else "• No fresh story text fetched."
        return (
            f"{sym} — {facts['name']}\n\n"
            f"I checked Yahoo + live news:\n"
            f"• Price: {px}\n"
            f"{news}\n\n"
            f"⚠️ Facts only — not a buy/sell call.\n"
            f"Want: (a) set a price alert (b) scan nifty50 (c) research another name ?"
        )

    def _self_tool(self, tool: str, args: dict, context: str) -> str:
        if tool == "web_search":
            q = args.get("query", "")
            hits = web_tools.news_digest(q, 5)
            if not hits:
                return "Search failed/blocked."
            return "\n".join(
                f"{i+1}. {h.get('title','')} | {h.get('body','')[:180]}"
                for i, h in enumerate(hits))
        if tool == "web_read":
            return web_tools.web_read(args.get("url", "")) or "Page read failed."
        if tool == "deepthink":
            return ai_router.consensus(args.get("question", ""), context) or "All AI busy."
        if tool == "update_models":
            return ai_router.auto_update_all()
        if tool == "update_self":
            return ai_router.do_self_update()
        return f"Unknown self tool {tool}"

    def _combine(self, reply: str, results: list) -> str:
        bits = [reply] if reply else []
        tail = "\n".join(results)[:1800]
        if tail:
            bits.append(tail)
        return "\n".join(bits).strip() or "Done."

    def _offline(self, text: str, executor, silent: bool = False) -> str:
        acts = rule_actions(text)
        bits = []
        for act in acts[:2]:
            try:
                if act["tool"] in SELF_TOOLS:
                    bits.append(self._self_tool(act["tool"], act.get("args", {}), ""))
                else:
                    bits.append(executor(act["tool"], act.get("args", {})))
            except Exception as e:
                bits.append(f"Failed: {e}")
        body = "\n".join(b for b in bits if b).strip() or "Try /help"
        msg = body if silent else ("(AI busy — tools only)\n" + body)
        self.mem.add("user", text)
        self.mem.add("assistant", msg)
        return msg


def rule_actions(text: str):
    t = text.strip().lower()
    if re.search(r"\bstatus\b", t):
        return [{"tool": "status", "args": {}}]
    if re.search(r"\b(pnl|profit|loss)\b", t):
        return [{"tool": "pnl", "args": {}}]
    if "position" in t:
        return [{"tool": "positions", "args": {}}]
    if "accura" in t or "win rate" in t:
        return [{"tool": "accuracy", "args": {}}]
    if t.strip() in ("scan",):
        return [{"tool": "scan", "args": {}}]
    if "task" in t:
        return [{"tool": "task_list", "args": {}}]
    m = re.search(r"cancel task #?(\d+)", t)
    if m:
        return [{"tool": "task_cancel", "args": {"id": int(m.group(1))}}]
    if re.search(r"squ[ae]re|squareoff|close all", t) and re.search(r"\b(if|when)\b", t):
        return [{"tool": "help", "args": {}}]
    if "square" in t or "close all" in t:
        return [{"tool": "squareoff", "args": {"symbol": "ALL"}}]
    t2 = re.sub(r"(?:qty|quantity|shares?|lots?|units?)\b", " ", t)
    m = re.search(r"\b(buy|sell)\s+(\d+(?:\.\d+)?)?\s*(?:of\s+)?([a-z&][a-z&.-]*)", t2)
    if m and "if " not in t:
        return [{"tool": m.group(1), "args": {"symbol": m.group(3).upper(),
                                              "qty": int(float(m.group(2) or 0))}}]
    m = re.search(r"(buy|sell|alert|notify)?\s*(\d+)?\s*([a-z&]+)\s+if\s+(above|below)\s+([\d.]+)", t)
    if m:
        verb = m.group(1) or "notify"
        action = {"buy": "buy", "sell": "sell"}.get(verb, "notify")
        return [{"tool": "task_create", "args": {
            "kind": "price_above" if m.group(4) == "above" else "price_below",
            "symbol": m.group(3).upper(), "level": float(m.group(5)),
            "action": action, "qty": int(m.group(2) or 0),
            "note": text[:80]}}]
    return [{"tool": "help", "args": {}}]
