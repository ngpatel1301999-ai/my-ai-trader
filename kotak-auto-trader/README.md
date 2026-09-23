# Kotak Neo Auto Trader v2 — SWING + AI Agent 🤖

**Swing equity (hold up to 2 weeks) + talk-to-it AI + auto-tasks while you're away.**
No TradingView needed. Phone (Telegram) is the remote.

## What the bot does

**SWING engine (BOT_MODE=swing, default)**
- Daily 3:20 PM scan: 20-day breakout + above EMA50 + uptrend + high volume (score ≥ 70)
- Auto exit: **SL −2% | T1 +5% (half out, SL→cost) | T2 +8% | 10-day time stop**
- BUY only (retail can't short delivery in India) | CNC product | max 3 positions
- Every exit saved in `swing_trades.csv` → real accuracy via `/accuracy`

**AI AGENT (chat in plain English on Telegram)**
- "buy 5 reliance" → trades (paper auto / live needs your ✅ tap or permission)
- "buy infy if below 1500" → saves TASK, bot executes while you're away 📌
- "square off all", "show pnl", "scan market", "my tasks", "cancel task 2"
- Brain = Google Gemini **FREE tier** key. No key? Basic keyword mode still works.

**TASKS (your assistant while sleeping)**
- Price tasks: IF RELIANCE above 3050 THEN buy / notify
- Time tasks: AT 2026-09-20 15:00 THEN squareoff_all
- Saved in `tasks.json`, survives restart. Telegram confirms when done.

**INTRADAY ORB still inside** — set BOT_MODE=intraday or both.

## Files

| File | Work |
|---|---|
| `main.py` | App brain + scheduler **+ FastAPI dashboard**. Run this. |
| `app.py` | 3-line wrapper so `uvicorn app:app` / `python app.py` also work |
| `paths.py` | Where state files live (`DATA_DIR` = mounted disk on Render) |
| `frontend/index.html` | Dashboard served at `/` (start/stop, status, positions) |
| `swing.py` | Swing score + position book + journal |
| `ai_agent.py` | Gemini chat → actions (stdlib only, no install) |
| `tasks.py` | Pending auto-tasks |
| `telegram_remote.py` | Commands + AI chat + Approve buttons |
| `kotak_client.py` | Login, quotes, orders, token search, daily history |
| `backtest_swing.py` | Measure REAL win-rate on daily CSV |
| `strategy.py` `datafeed.py` `paper.py` `risk.py` | Intraday ORB parts |

## SETUP — Step 1: Kotak Neo API (15 min, one time)

1. Neo app → **More → Trade API → API Dashboard → Create Application** → token = `NEO_CONSUMER_KEY`
2. **TOTP Registration** → scan QR + **save the secret text** = `NEO_TOTP_SECRET`
3. Note **UCC** + **6-digit MPIN**
4. Paper phase: whitelist laptop IP (whatsmyip.com). LIVE later: VPS static IP.

## SETUP — Step 2: Telegram (5 min, free)

@BotFather → /newbot → token. @userinfobot → your numeric id. Open bot → START.

## SETUP — Step 3: FREE AI key (5 min)

1. Open https://aistudio.google.com → **Get API key** (free) → paste as `GEMINI_API_KEY`
2. Works without key too (basic mode), but AI chat is much smarter with key.

## SETUP — Step 4: Install + run (laptop)

```bash
cd kotak-auto-trader
pip install -r requirements.txt
cp .env.example .env        # fill keys in .env (NEVER share it)
python backtest_swing.py --generate-sample
python backtest_swing.py --csv swing_sample.csv     # plumbing test
python main.py              # PAPER swing + AI. Nothing real happens.
```

## SETUP — Step 4b: Deploy on Render (cloud, 24×7) ☁️

One process serves **both**: the Telegram/trading bot (daemon thread) and the
web dashboard (FastAPI). Render needs a port, so the web server is the front
door and the bot auto-starts with it.

**Render dashboard → your service → Settings**

| Setting | Value |
|---|---|
| Root Directory | `kotak-auto-trader` |
| Runtime | Python |
| Build Command | `pip install -r requirements.txt` |
| Start Command | `python main.py` |
| Health Check Path | `/health` |

**Environment → add** (these are the ones that fixed the broken deploy):

```
PYTHON_VERSION = 3.12.8      # Render defaults to 3.14.3 = too new for pandas/pydantic wheels
DATA_DIR       = /var/data   # only if you attach a Disk (see below)
BOT_AUTOSTART  = true        # false = bot waits for you to press Start on the dashboard
```
Plus your secrets: `NEO_CONSUMER_KEY`, `NEO_MOBILE_NUMBER`, `NEO_UCC`, `NEO_MPIN`,
`NEO_TOTP_SECRET`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `GEMINI_API_KEY`,
`BOT_MODE=swing`, `TRADING_MODE=paper`, `ENABLE_LIVE_ORDERS=false`.

**Then:** Disks → Add disk → Mount path `/var/data`, 1 GB.
Without a disk, `tasks.json` / `swing_positions.json` / `swing_trades.csv` are
**wiped on every deploy** (Render's disk is ephemeral).

**Check it worked**

1. Logs show `Uvicorn running on http://0.0.0.0:10000` **and** `Telegram remote is live`
2. Open your service URL → dashboard. Status should read `RUNNING`.
3. `https://YOUR-SERVICE.onrender.com/api/log?lines=50` → tail of `trades.log`
4. Telegram: send `/status`

**⚠️ Two Render gotchas for a trading bot**

- **Kotak IP whitelist:** Render's outbound IP changes on redeploy, so
  `script-details/*` (token search) will reject you. The bot survives this —
  it uses the built-in token map + `historical-data` and starts in
  **ASSISTANT MODE** (chat/research/tasks work, Kotak retried every 5 min).
  For real trading use an Indian VPS with a static IP (Step 5).
- **Free plan sleeps** after ~15 min with no HTTP traffic → Telegram polling
  stops. Use a paid instance (or an uptime pinger on `/health`) if you need it
  always listening.

## SETUP — Step 5: Go LIVE (only after 1 profitable paper month)

1. Indian VPS + static IP (~₹500–1,000/month), whitelist IP in Kotak dashboard
2. `.env`: `TRADING_MODE=live` **AND** `ENABLE_LIVE_ORDERS=true`
3. AI live: `AI_TRADING_ENABLED=true`. Keep `AI_REQUIRE_APPROVAL=true` at first
   (AI asks, you tap ✅). Full-auto only when you truly trust it.
4. Small size: `RISK_PER_TRADE_RS=500`, `MAX_POSITION_VALUE_RS=10000` to start

## AI permission locks (ONLY you change these in .env — AI cannot)

| Setting | Meaning |
|---|---|
| `AI_PAPER_TRADING=true` | AI may trade fake money |
| `AI_TRADING_ENABLED=false` | AI may touch REAL money (default OFF) |
| `AI_REQUIRE_APPROVAL=true` | Live AI trades need your ✅ tap |
| `AI_MAX_ORDER_VALUE_RS=10000` | Single AI order value cap |

Plus always-on guards: max positions, max/day, daily loss stop, kill switch, CNC only.

## Mobile: what to type

- `status` `show pnl` `my positions` `accuracy` `scan` `my tasks`
- `buy 5 reliance` `sell infy` `square off all`
- `alert me if tcs above 4400` `buy 2 sbin if below 800` `cancel task 3`
- Commands also work: /status /pnl /positions /accuracy /tasks /scan /buy /sell /stop /resume /squareoff

## Agent v2 — AI that understands like an assistant 🧠

Your Telegram AI now works like me:
- **Understands intent**: "buy reliance" → auto qty from YOUR risk settings. No qty needed.
- **Follow-ups**: "same for infy", "no — 10 qty", "cancel that" (remembers last 8 turns)
- **Multi-step plans**: "buy the best stock from today's scan" → scans → picks → buys (asks ✅ in live)
- **Self-fixes**: wrong spelling / failed price / failed order → retries differently, asks only if stuck
- **Remembers**: "remember I avoid PSU banks" → saved. "forget" → clears memory.
- **Your language**: English / Hindi / Hinglish auto-matched
- **Never sleeps**: run with `./supervise.sh` (chmod +x first) — auto-restarts if it ever crashes

## Multi-AI brain — 28 slots, self-updating 🧠🧠

One AI can fail or be wrong. Yours uses a **chain of AIs** (free first).
Add keys → they auto-join. No key → skipped. Local laptop AI supported too.

**FREE keys (5 min each):** Groq, Cerebras, OpenRouter, Together, Fireworks,
SambaNova, HuggingFace, GitHub Models ← uses YOUR GitHub account!,
NVIDIA build.nvidia.com, Nebius, Zhipu (GLM free), SiliconFlow. (Pollinations free tier is blocked in some regions — auto-skipped if so.)
**Local (laptop, fully free):** install Ollama → add `ollama` to AI_PROVIDERS.
**Paid (add anytime):** OpenAI, Anthropic, xAI/Grok, Mistral, Kimi, DeepSeek, Perplexity, Cohere, Qwen, Hyperbolic.
**Anything else:** CUSTOM1_BASE/KEY/MODEL fits ANY OpenAI-compatible endpoint.

- **`update your all ai`** → fetches every provider's model list, switches to **latest versions**, shows `old → new` report. Saved in `ai_models.json`.
- **`ask all ai: is INFY a good buy?`** → several AIs answer, merged into ONE precise verdict.
- **`research RELIANCE deeply`** → live web news + pages → Bullish/Bearish/Neutral + reasons.
- **`update yourself`** → git pull + reinstall + restart (≈30 sec, positions/tasks safe).

## Answers like Arena 💬

Your bot now answers like a top AI assistant:
- **Short confirmations**: "🟢 Bought RELIANCE x4 @3020. SL 2959 | T1 3171 | T2 3261" — no noise.
- **Full answers** for questions/research: direct answer first → lists/tables → ⚠️ honest risk line → `Want: (a)... (b)...?`
- Long answers auto-split into `(part 1) (part 2)` — nothing gets cut on Telegram.
- Ask: `research TITAN deeply` or `compare INFY vs TCS for swing` to see the style.

## Honest math (read!)

- Nobody can promise 70% accuracy. With −2% / +5–8%, even **35% wins = profit**.
- Tight 2% SL on swing = more stop-outs. If win-rate is low in backtest, try `--sl 3 --t1 6 --t2 9`.
- Backtest needs **2+ years REAL daily data** (Kotak history only gives ~180 days; stitch more from other free sources).
- Start live tiny. Scale only after 2–3 green months.

## Troubleshooting

- **`TypeError: Flask.__call__() missing 2 required positional arguments`** →
  you are on the old `main.py`. It did `from app import app` (the Flask object)
  and then called `app()` instead of `App()`. Fixed: `app.py` is now a wrapper,
  `main.py` has no Flask at all. Pull the latest.
- **`GET /` returns 404 on Render** → the old first FastAPI app had no `/`
  route. Now `/` serves the dashboard and accepts HEAD (Render's probe).
- **Bot thread dies but the service stays "live"** → check `/api/status` →
  `bot` must be `running`; `error` and `telegram` fields tell you why not.
- TOTP wrong → phone clock must be exact (automatic time ON)
- "IP not whitelisted" → IP changed; update in Kotak dashboard (Render IPs rotate —
  use a VPS for live)
- AI dumb replies → check GEMINI_API_KEY; free quota resets daily
- Order rejected → low margin / BE-category stock / market closed → check Neo app + trades.log
- Swing sell fails → BTST/T2T limits; stick to liquid largecaps
- Tasks/positions vanished after a deploy → set `DATA_DIR=/var/data` and attach a Disk

⚠️ Educational code. You are responsible for your orders. Start tiny.
