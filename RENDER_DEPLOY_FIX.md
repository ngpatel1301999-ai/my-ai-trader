# 🔧 Render deploy fix — what was broken and what to do now

Date: 2026-09-23 · Repo: `ngpatel1301999-ai/my-ai-trader` · Service: `my-ai-trader-dlxq`

Your build succeeded but the bot never ran. There were **3 separate bugs** — the
crash you pasted is only the first one.

---

## Bug 1 (the crash): `app` meant two different things

```
File ".../main.py", line 55, in run_trading_bot
    bot_app = app()
TypeError: Flask.__call__() missing 2 required positional arguments: 'environ' and 'start_response'
```

Line 13 of `main.py` was:

```python
from app import app        # <- this "app" is the FLASK object from app.py
```

and `main.py` also defined `class App:` (the bot brain). So inside
`run_trading_bot()` the name `app` was the **Flask instance**, not the bot class.
Calling a Flask instance means "handle a WSGI request", which is why Python asked
for `environ` and `start_response`.

Result: the bot thread died instantly → no Telegram, no trading. The web server
kept running, so Render still said *"Your service is live 🎉"*.

**Fix:** `app.py` is now a 3-line wrapper around FastAPI (no Flask, no
subprocess). `main.py` no longer imports it, so `App` is unambiguous.

> The old `app.py` also did `subprocess.Popen([sys.executable, "main.py"])` — on a
> host like Render that means a **second** bot process, a second Telegram poller
> and duplicate replies. Gone.

## Bug 2 (the 404s): the wrong FastAPI app was serving

`main.py` had the FastAPI block **pasted twice** — once at the top (lines 20-64)
and once at the bottom (lines 1695-1742). Python ran the top one, which had no
`/` route, and the `if __name__ == "__main__"` at the bottom never executed:

```
INFO: 127.0.0.1:51984 - "HEAD / HTTP/1.1" 404 Not Found     <- Render's health probe
INFO: 35.185.236.171:0 - "GET / HTTP/1.1" 404 Not Found     <- your browser
```

Also, everything after the first `uvicorn.run()` (all the imports, `logging`,
`App`, `main()`) was in the wrong order, and `main()` was placed *after*
`uvicorn.run()`, so it could never run.

**Fix:** one FastAPI app (`web_app`), imports at the top, bot in a daemon thread,
web server in the main thread:

| Route | What it does |
|---|---|
| `GET/HEAD /` | dashboard (`frontend/index.html`) — 200, so Render is happy |
| `GET/HEAD /health` | `{"ok":true,"bot":"running","uptime_s":…}` |
| `GET /api/status` | bot state, paper/live, Kotak + Telegram truth, build |
| `GET /api/positions` | swing + commodity positions (runs in a threadpool, so a slow LTP call can't block the server) |
| `GET /api/tasks` | open equity + commodity tasks |
| `GET /api/log?lines=120` | tail of `trades.log` (Render has no file browser) |
| `POST /start` · `POST /stop` | start/stop the bot thread (no second process) |

`HEAD` is registered explicitly — Render probes with `HEAD /`, and FastAPI's
`@app.get` answers HEAD with **405**, which also counts as unhealthy.

## Bug 3: missing Kotak keys killed the whole bot

`main()` did this:

```python
problems = SETTINGS.validate()
if problems:
    print("❌ Fix .env first:")
    return          # <- bot never starts, Telegram never connects
```

On Render, if even one env var is missing/typo'd (very common: `NEO_TOTP_SECRET`),
the bot exited before Telegram started — and you'd see no error, just silence.

**Fix:** the bot now always starts. Missing keys → **ASSISTANT MODE**
(chat/research/tasks work), Kotak retried every 5 minutes, and the reason is
logged + shown on the dashboard + in `/api/status`.

---

## Everything that changed

| File | Change |
|---|---|
| `kotak-auto-trader/main.py` | Rewrote the top (imports/logging) and the bottom (bot runner + FastAPI). `App` class and all trading logic untouched. |
| `kotak-auto-trader/app.py` | Flask + subprocess → thin FastAPI wrapper (`uvicorn app:app` still works) |
| `kotak-auto-trader/telegram_remote.py` | Added `self.error` so a dead poller / bad token is reported honestly instead of showing green |
| `kotak-auto-trader/paths.py` | **NEW** — `DATA_DIR` support (state files on a mounted disk) |
| `swing.py` `tasks.py` `commodity.py` `memory.py` `risk.py` `kotak_client.py` | State files (`swing_positions.json`, `tasks.json`, `swing_trades.csv`, `memory.json`, `KILLSWITCH`, `tokens_verified.json`) now live in `paths.data_dir()` |
| `frontend/index.html` | Hard-coded `https://my-ai-trader-dlxq.onrender.com` → same-origin `""` (no CORS, survives a rename). Added Start/Stop buttons, Kotak/Telegram state, uptime, auto-refresh |
| `requirements.txt` | Pinned + removed `flask`, added `tzdata` (for `ZoneInfo("Asia/Kolkata")`) |
| `.python-version` | **NEW** — `3.12` (Render's default is 3.14.3 = too new, wheels missing) |
| `render.yaml` | **NEW** — blueprint for a fresh service (optional) |
| `smoke_test.py` | **NEW** — `python smoke_test.py` checks all 13 things before you push |
| `.gitignore` | + `logs/`, `trades.log`; removed 4 committed log files (4,348 lines of noise) |
| `kotak-auto-trader/README.md` | New "Step 4b: Deploy on Render" + troubleshooting entries |

---

## ✅ What YOU must do (code alone is not enough)

### 1. Push the fix

```bash
cd my-ai-trader
git pull                                  # only if you also edit on another machine
# copy the fixed files in (or: git apply render-deploy-fix.patch)
python smoke_test.py                      # must print "All checks passed"
git add -A
git commit -m "Fix Render deploy: app/App name clash, duplicate FastAPI app, assistant mode, Python 3.12, DATA_DIR"
git push origin main
```

### 2. Render dashboard → your service → **Settings**

| Setting | Value |
|---|---|
| Root Directory | `kotak-auto-trader` |
| Build Command | `pip install -r requirements.txt` |
| Start Command | `python main.py` |
| Health Check Path | `/health` |

### 3. Render dashboard → **Environment** → add

```
PYTHON_VERSION = 3.12.8
DATA_DIR       = /var/data
BOT_AUTOSTART  = true
BOT_MODE       = swing
TRADING_MODE   = paper
ENABLE_LIVE_ORDERS = false
```

and the secrets: `NEO_CONSUMER_KEY`, `NEO_MOBILE_NUMBER`, `NEO_UCC`, `NEO_MPIN`,
`NEO_TOTP_SECRET`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `GEMINI_API_KEY`.

> `PYTHON_VERSION` has the **highest precedence** on Render (higher than
> `.python-version`). Without it you stay on 3.14.3.

### 4. Render dashboard → **Disks** → Add disk

Mount path `/var/data`, size 1 GB. Without it, `tasks.json`,
`swing_positions.json` and `swing_trades.csv` are **wiped on every deploy** —
Render's filesystem is ephemeral. (The `.env` values are safe; only files the
bot writes are lost.)

### 5. Save → **Manual Deploy → Deploy latest commit**, then watch the logs

Healthy log looks like this:

```
BUILD main=2026-09-20j agent=2026-09-20j kotak_client=2026-09-17d
Web on http://0.0.0.0:10000  |  data dir: /var/data
INFO:  Uvicorn running on http://0.0.0.0:10000
INFO:  autostart: Bot launched - Telegram + trading loop starting.
INFO:  telegram: Telegram remote ON
INFO:  main: Telegram remote is live
INFO:  127.0.0.1:0 - "HEAD /health HTTP/1.1" 200 OK
```

**No** `TypeError`, **no** `404` on `/`.

Then open `https://my-ai-trader-dlxq.onrender.com/` → the dashboard should say
**RUNNING**, and Telegram `/status` should answer.

---

## ⚠️ Two Render realities for a trading bot (read before going live)

1. **Kotak IP whitelist.** Render's outbound IP changes on every deploy, so
   Kotak's `script-details/*` endpoints (token search) will reject you — you'll
   see HTTP 424 `Consumer key ... is invalid`. The bot survives this: it uses the
   built-in token map + `historical-data`, and stays in ASSISTANT MODE while
   retrying. **For real orders you need a static IP** → an Indian VPS
   (₹500–1,000/month) with that IP whitelisted in the Kotak dashboard.
2. **Free plan sleeps** after ~15 min without HTTP traffic → Telegram polling
   stops and your bot goes deaf. Use a paid instance, or ping `/health` from an
   uptime checker every 5–10 min.

Also: **never run 2+ workers** (`--workers 2`, `WEB_CONCURRENCY=2`). More workers
= more bots = duplicate Telegram replies and duplicate orders. The code pins
`workers=1` in `serve_web()`.

---

## 🩺 If it still fails, check in this order

| Symptom in the log | Meaning | Fix |
|---|---|---|
| `Config incomplete -> ASSISTANT MODE` + a list | env vars missing on Render | add them (step 3) |
| `telegram: polling stopped: The token ... was rejected` | wrong `TELEGRAM_BOT_TOKEN` | new token from @BotFather |
| `Telegram not configured — mobile remote OFF` | token/chat id still `PASTE...` | set real values |
| `Kotak login FAILED: Non-base32 digit` | `NEO_TOTP_SECRET` is not the base32 secret | copy the secret text from the TOTP QR screen |
| `"IP not whitelisted"` / HTTP 424 | Render IP not in Kotak dashboard | VPS with static IP |
| `HEAD /health 503` / service restarts | health check failing | Health Check Path must be `/health` |
| Nothing at all after `Uploaded build` | wrong Root Directory | must be `kotak-auto-trader` |

`GET /api/log?lines=200` on your service URL shows the same `trades.log` the bot
writes — fastest way to debug without the Render console.

---

## Verified locally (all passing)

```
ok   import main + app (no Flask/app() clash)
ok   all web routes exist
ok   / accepts HEAD (Render health probe)
ok   GET  /            -> 200 dashboard
ok   GET  /health      -> 200 ok:true
ok   GET  /api/status  -> 200
ok   GET  /api/positions -> 200 + list
ok   GET  /api/tasks   -> 200
ok   GET  /api/log     -> 200
ok   POST /start       -> bot running
ok   POST /start again -> refused (no double bot)
ok   POST /stop        -> bot stopped
```
Plus real servers on ports 10000/10001/10002 via `python main.py`,
`uvicorn main:web_app`, and `uvicorn app:app`.
