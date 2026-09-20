# 🎯 MASTER PLAN — Your AI Trading System (First Step → Fully Working)

Everything you asked, in order, within your resources (laptop + phone + Kotak + free tools).
**Total cost to start: ₹0.** Only future cost: VPS ~₹500–1,000/month when you go LIVE.

Tick boxes as you finish. Do NOT skip phases.

---

## PHASE 0 — Accounts & Keys (TODAY, ~1 hour, ₹0)

- [ ] **0.1 Kotak Neo API (15 min)** — Neo app → More → Trade API → API Dashboard
  - Create Application → copy token (`NEO_CONSUMER_KEY`)
  - TOTP Registration → scan QR in Google Authenticator → **save secret text** (`NEO_TOTP_SECRET`)
  - Note UCC (Profile) + 6-digit MPIN
  - Add IP → your current IP (google "whatsmyip") → Update
  - ✅ Works when: token + secret + UCC + MPIN written down safely
- [ ] **0.2 Telegram remote (5 min, on phone)**
  - @BotFather → /newbot → copy token (`TELEGRAM_BOT_TOKEN`)
  - @userinfobot → copy your numeric id (`TELEGRAM_CHAT_ID`)
  - Open your new bot → press START
- [ ] **0.3 FREE Gemini key (5 min)** — aistudio.google.com → Get API key (`GEMINI_API_KEY`)
- [ ] **0.4 FREE Groq key (5 min)** — console.groq.com → signup → API keys (`GROQ_API_KEY`)
- [ ] **0.5 GitHub Models key (10 min)** — github.com → Settings → Developer settings → Personal access tokens → Fine-grained → permission **Models: Read** (`GITHUB_TOKEN`)
- [ ] **0.6 Python on laptop (10 min)** — python.org → download → install → **TICK "Add python to PATH"** → restart terminal → check: `python --version`

## PHASE 1 — First Paper Run (TODAY/TOMORROW, ~1 hour, ₹0)

- [ ] **1.1 Get the project** — download the `kotak-auto-trader` folder from this workspace (file panel) to your laptop. OR: `git init` it and push to YOUR GitHub (needed later for VPS).
- [ ] **1.2 Install** — open terminal in that folder:
  ```
  pip install -r requirements.txt
  copy .env.example .env        (Windows)  /  cp .env.example .env  (Mac)
  ```
- [ ] **1.3 Fill `.env`** — paste ALL keys from Phase 0. Keep `TRADING_MODE=paper`, `BOT_MODE=swing`. NEVER share this file.
- [ ] **1.4 Plumbing test (works anytime)** — `python backtest_swing.py --generate-sample` then `python backtest_swing.py --csv swing_sample.csv` → you see BUY/exit lines + RESULT.
- [ ] **1.5 LIVE paper run (market hours 9:15–15:30, Mon–Fri)** — `python main.py`
  - ✅ Works when: phone Telegram gets "🤖 Bot started: SWING 🟢 PAPER"
- [ ] **1.6 Talk to your AI (the fun part)** — on Telegram, type:
  - `status` → `scan` → `buy RELIANCE` → `my positions` → `square off all`
  - `research TITAN deeply` → `ask all ai: is INFY a good swing buy?`
  - `update your all ai` → `buy 2 SBIN if below 800` (task!) → `my tasks`
  - ✅ Works when: AI answers in full style with tables + options, like I answer you

## PHASE 2 — Morning Brief + Testing Loop (THIS WEEK, ₹0)

- [ ] **2.1 Brief test** — `python morning_brief.py` (any morning) → brief lands on Telegram + `brief_YYYY-MM-DD.md` file.
- [ ] **2.2 Let paper swing run daily** — laptop ON 9:15–3:30 on working days. Watch Telegram: entries ~3:20 PM scan, SL/T1/T2 auto-exits.
- [ ] **2.3 Weekly review (Sunday)** — type `/accuracy` → note win-rate + total. Goal before LIVE: **4 weeks paper + you understand every trade in `swing_trades.csv`.**
- [ ] **2.4 (Optional) Real backtest** — get 1+ year NSE daily data CSV → `python backtest_swing.py --csv YOUR.csv --sl 2 --t1 5 --t2 8`. If win-rate < 35%, try `--sl 3 --t1 6 --t2 9` and tell me results — I'll retune rules.

## PHASE 3 — Video-Type Chart AI (WEEKEND, ~2 hours, ₹0)

Your analyst brain on laptop (like Sumedhh's video, but FREE + NSE + Kotak-ready).
- [ ] **3.1 Install** — Node.js 18+ (nodejs.org) + Git (git-scm.com) + TradingView Desktop (tradingview.com/desktop).
- [ ] **3.2 Gemini CLI** — terminal: `npm install -g @google/gemini-cli` → run `gemini` → login with Google (free 1000 req/day).
- [ ] **3.3 One-shot setup** — in terminal go to `ai-chart-agent` folder → paste **Section A prompt** from `MASTER_PROMPT.md` → AI wires the TradingView MCP itself → health check passes.
- [ ] **3.4 First chart commands** — `Show my watchlist` → morning-brief prompt (Section B) → `draw support-resistance on NSE:RELIANCE 1D`.
- [ ] **3.5 Pine Script** — paste `PINE_SWING_STRATEGY.pine` into TradingView Pine Editor → Add to chart (1D) → read Strategy Tester (profit %, win-rate, drawdown).
- [ ] **3.6 Improve loop** — Section D prompts, max 3 tries. Keep a change ONLY if profit AND win-rate both improve.

## PHASE 4 — Go LIVE (ONLY after 4 green-ish paper weeks, ~₹500–1,000/month)

- [ ] **4.1 Indian VPS + static IP** (Hostinger India / AWS Mumbai / etc.) → install Python + Git → clone YOUR GitHub repo → copy `.env`.
- [ ] **4.2 Whitelist VPS IP** in Kotak API Dashboard (SEBI rule — mandatory).
- [ ] **4.3 Tiny-live settings** in VPS `.env`: `TRADING_MODE=live` + `ENABLE_LIVE_ORDERS=true` + `RISK_PER_TRADE_RS=500` + `MAX_POSITION_VALUE_RS=10000` + keep `AI_REQUIRE_APPROVAL=true`.
- [ ] **4.4 Run forever** — `chmod +x supervise.sh` → `nohup ./supervise.sh &` (auto-restart if crash).
- [ ] **4.5 First 2 live weeks** — approve every AI trade manually (✅/❌). Laptop can stay OFF. Phone = full control.
- [ ] **4.6 Full-auto (your choice, later)** — only after 1 profitable live month: `AI_REQUIRE_APPROVAL=false`. Tasks already run auto.

## PHASE 5 — Daily Routine (10 min/day, forever)

| When | You do |
|---|---|
| 8:45 AM | Read Telegram morning brief ☀️ (auto) |
| 9:00 AM | (Optional) Ask chart-AI anything |
| 3:20 PM | Bot auto-scan; approve ✅/❌ if asked |
| Anytime | Chat: tasks, pnl, squareoff — from anywhere |
| Sunday | `/accuracy` review + `update your all ai` + `update yourself` |

---

## 🔴 RED LINES (never break)

1. Paper 4 weeks before LIVE. No exceptions.
2. Start LIVE tiny (₹500 risk/trade). Scale only after green months.
3. Never share `.env` / MPIN / TOTP with ANYONE (no "algo seller" needs them).
4. Anyone promising fixed profit/70% accuracy = fraud. Your bot MEASURES accuracy; nobody guarantees it.
5. Keep approvals ON until you fully trust it.

## 📁 Your files (this workspace)

| File/Folder | What |
|---|---|
| `MASTER_PLAN.md` | ← YOU ARE HERE (the full journey) |
| `kotak-neo-auto-trading-guide.md` | Concepts + Kotak activation |
| `kotak-auto-trader/` | The bot (swing + AI + tasks + brief + research) |
| `ai-chart-agent/` | Video-type system (rules.json, prompts, Pine, setup) |

**Stuck anywhere? Come back here and tell me the step number + error text — I'll fix it with you.** 🤝
