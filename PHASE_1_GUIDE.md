# ✅ PHASE 1 — First Paper Run + Talk to Your AI (~1 hour, ₹0)

**Goal:** bot running on laptop (fake money) + you chatting with your AI on phone.

---

## 1.1 Get the project on laptop (10 min)

1. In this workspace (file panel), find **`my-ai-trader.zip`** → **Download** it to laptop.
2. Extract it → you get folders `kotak-auto-trader/` + `ai-chart-agent/` + guides.
3. (Recommended) Push to YOUR GitHub for backup + later VPS use:
   ```
   cd my-ai-trader-folder
   git init
   git add .
   git commit -m "my ai trader"
   ```
   Then create empty repo on github.com → follow its 3 push commands.
   ⚠️ `.env` is auto-ignored (see `.gitignore`) — your keys NEVER go to GitHub. Verify: `git status` must NOT show `.env`.

## 1.2 Install (10 min)

1. Open terminal **inside** `kotak-auto-trader/` folder:
   - Windows: open folder → click address bar → type `powershell` → Enter.
2. Run:
   ```
   pip install -r requirements.txt
   ```
   (Takes 2–5 min. Ignore yellow warnings; only red ERROR matters.)
3. Copy settings template:
   ```
   copy .env.example .env        (Windows)
   cp .env.example .env          (Mac)
   ```

## 1.3 Fill `.env` (10 min) — open `.env` in Notepad, paste Phase-0 keys:

```
BOT_MODE=swing
TRADING_MODE=paper
ENABLE_LIVE_ORDERS=false
NEO_CONSUMER_KEY=<0.1 step 4 token>
NEO_MOBILE_NUMBER=+91XXXXXXXXXX     (registered mobile WITH +91, no spaces)
NEO_UCC=<client code, e.g. AB1234>
NEO_MPIN=<6 digits>
NEO_TOTP_SECRET=<0.1 step 9 secret, NO spaces>
TELEGRAM_BOT_TOKEN=<123456:ABC...>
TELEGRAM_CHAT_ID=<numbers only>
GEMINI_API_KEY=<AIza...>
GROQ_API_KEY=<gsk_...>
GITHUB_TOKEN=<github_pat_...>
AI_PROVIDERS=gemini,groq,github_models
WATCHLIST=RELIANCE,INFY,TCS,HDFCBANK
```
Keep everything else as default. **SAVE the file.**
Start with 4 stocks only — add more after a week.

## 1.4 Plumbing test (5 min, works ANYTIME — no login needed)

In the same terminal:
```
python backtest_swing.py --generate-sample
python backtest_swing.py --csv swing_sample.csv
```
✅ **Works when:** you see `BUY ... score ...` lines + final `RESULT: trades=... WinRate=...`.
(This uses random dummy data — just proves the engine runs. Real test comes later.)

## 1.5 LIVE paper run (market hours 9:15–15:30, Mon–Fri)

```
python main.py
```
- First 30 sec: it resolves stock tokens + logs into Kotak + starts Telegram.
- ✅ **Works when:** phone Telegram gets `🤖 Bot started...`.
- **No Kotak yet?** Bot starts in 🔌 **assistant mode** — chat/research/tasks work, trading waits + auto-reconnects every 5 min. Fix the key anytime, no restart needed.
- Leave laptop ON + terminal open during market hours. Minimize, don't close.
- **Market closed right now?** Still run it — bot waits patiently, and **Telegram chat works 24×7** (only live prices/orders need market hours).

## 1.6 Talk to your AI 🤖 (the fun part — 15 min)

On Telegram, send these IN ORDER, watch replies:

| # | You type | Expected |
|---|---|---|
| 1 | `status` | Mode PAPER, login yes/no, AI trade ON |
| 2 | `scan` | 4 stocks with scores (needs market data; off-hours may show weak/old) |
| 3 | `buy RELIANCE` | 🟢 PAPER BUY + SL/T1/T2 table (needs market hours for price) |
| 4 | `my positions` | Shows the RELIANCE paper position |
| 5 | `square off all` | Closes it, shows P&L |
| 6 | `research TITAN deeply` | Web news + Bullish/Bearish verdict (works 24×7!) |
| 7 | `ask all ai: is INFY good for swing?` | Multi-AI consensus (works 24×7!) |
| 8 | `alert me if TCS above 4500` | 📌 Task saved (bot watches while you're away) |
| 9 | `my tasks` | Lists task #1 |
| 10 | `cancel task 1` | Task cancelled |
| 11 | `update your all ai` | Model upgrade report per provider |
| 12 | `accuracy` | "No closed trades yet" (fills up as paper trades close) |

✅ **Phase 1 works when:** steps 1, 6, 7, 8, 11 answer nicely. (Steps 2–5 need market hours.)

---

## 🛠️ If something fails — FIRST run the doctor:

```
python doctor.py
```
It checks .env → IP → token → login → prices step by step and tells you the exact fix. Paste its output here if stuck.

| Problem | Fix |
|---|---|
| `pip` not recognized | Python PATH issue → redo Phase 0.6 (tick Add to PATH), open NEW terminal |
| `ModuleNotFoundError: ...` | Run `pip install -r requirements.txt` again in the RIGHT folder (must contain `main.py`) |
| `Fix .env first: ...` | That key is blank/wrong in `.env` → open, paste, SAVE |
| Login FAILED / TOTP wrong | Phone clock must be automatic-time; secret must have NO spaces; retry |
| `IP not whitelisted` | IP changed → Kotak Dashboard → Add IP (new from whatsmyip.com) |
| Telegram silent | Wrong BOT_TOKEN/CHAT_ID? Did you press START in bot chat? Restart `main.py` |
| AI says "Basic mode" | Gemini/Groq key wrong or quota over → check keys, retry in 1 min |
| Any red traceback | Copy FULL error → send it here with step number → I'll fix with you 🤝 |

## 🎉 PHASE 1 DONE — check

- [ ] `main.py` runs without errors
- [ ] Phone got "🤖 Bot started" message
- [ ] AI answered chat tests (esp. 1, 6, 7, 8, 11)

**Now say "Phase 1 done" + paste ONE AI reply you liked — then we start Phase 2 (morning brief + testing loop).** 🚀
