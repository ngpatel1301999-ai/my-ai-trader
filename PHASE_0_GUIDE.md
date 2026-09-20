# ✅ PHASE 0 — Detailed Step-by-Step (Accounts & Keys, ~1 hour, ₹0)

Do steps 0.1–0.5 on your **phone**. Step 0.6 on your **laptop**.
Keep all keys in ONE safe place (password manager or diary). NEVER share with anyone.

**Your Key Diary** — fill as you go:
```
NEO_CONSUMER_KEY=
NEO_MOBILE_NUMBER=+91..........
NEO_UCC=
NEO_MPIN=...... (6 digits)
NEO_TOTP_SECRET=
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
GEMINI_API_KEY=
GROQ_API_KEY=
GITHUB_TOKEN=
MY_LAPTOP_IP=
```

---

## 0.1 Kotak Neo API (15 min) — THE most important step

1. Open **Kotak Neo app** on phone → login.
2. Tap **More** (bottom/side menu) → tap **Trade API** card → you see **API Dashboard**.
3. Tap **Create Application** (or Generate) → name it `MyBot` → tap Create.
4. A long **token** appears → **COPY it** → save as `NEO_CONSUMER_KEY`. (This is like a password!)
5. Same screen → tap **menu (⋮ top-right)** → **TOTP Registration**.
6. Enter your registered mobile number → tap Get OTP → enter OTP.
7. Screen shows a **QR code + a secret key TEXT** (long CAPITAL letters).
8. Open **Google Authenticator** app (install from Play Store if needed) → **+** → **Enter a setup key** → Name: `KotakNeo` → paste the secret → Add.
9. **WRITE that secret text** in your diary as `NEO_TOTP_SECRET` (bot needs it for daily auto-login).
10. Authenticator now shows 6 digits changing every 30 sec → type current 6 digits into Kotak screen → Submit. ✅ TOTP done.
11. Go to **Profile** section → find **Client Code / UCC** (like AB1234) → save as `NEO_UCC`.
12. Your **6-digit trading MPIN** (the one you enter to place orders) → save as `NEO_MPIN`. Forgot it? Profile → Settings → Change MPIN.
13. On phone/laptop browser open **whatsmyip.com** → note your IP (e.g. 49.37.x.x).
14. Back in Kotak **API Dashboard** → **Add IP** → paste that IP → tick "I agree" → **Update**.
15. ✅ **Check:** diary has token + secret + UCC + MPIN + IP. Done!

> Note: home IP sometimes changes. If bot later says "IP not whitelisted", just repeat step 14 with the new IP. (VPS static IP in Phase 4 fixes this forever.)

## 0.2 Telegram remote (5 min)

1. Install **Telegram** → login with your number.
2. Search **@BotFather** (verified, blue tick) → tap START → send `/newbot`.
3. It asks bot name → send `My Trade Bot` (any name).
4. It asks username → send something unique ending in `bot`, e.g. `my_trade_rohit_2026_bot`. If taken, try another.
5. BotFather replies with a long **HTTP API token** (like `123456:ABC...`) → save as `TELEGRAM_BOT_TOKEN`.
6. Search **@userinfobot** → START → it replies your **numeric id** (like `7123456789`) → save as `TELEGRAM_CHAT_ID`.
7. Search YOUR new bot by its username → open chat → tap **START**. ⚠️ (Skip this = bot can't message you!)
8. ✅ **Check:** token + numeric id saved, bot chat started.

## 0.3 FREE Gemini key (5 min)

1. Browser → **aistudio.google.com** → Sign in with Google.
2. Click **Get API key** (left/top) → **Create API key** → select project (default ok) → Create.
3. COPY key (starts with `AIza...`) → save as `GEMINI_API_KEY`. Free forever tier. ✅

## 0.4 FREE Groq key (5 min)

1. Browser → **console.groq.com** → Sign up with Google.
2. Left menu → **API Keys** → **Create API Key** → name `kotak-bot` → Create.
3. COPY key (starts with `gsk_...`) → save as `GROQ_API_KEY`. ⚠️ Shown ONCE — copy now! ✅

## 0.5 GitHub Models key (10 min) — bonus FREE smart AI using YOUR GitHub

1. Browser → **github.com** → login.
2. Top-right **profile photo → Settings** → scroll bottom-left → **Developer settings**.
3. **Personal access tokens → Fine-grained tokens** → **Generate new token**.
4. Token name: `bot-models` → Expiration: 90 days (or custom 1 year).
5. Scroll to **Permissions → Account permissions** → find **Models** → set to **Read-only (Access: Read)**.
6. Click **Generate token** → COPY (starts with `github_pat_...`) → save as `GITHUB_TOKEN`. ⚠️ Shown ONCE! ✅

## 0.6 Python on laptop (10 min)

**Windows:**
1. Browser → **python.org** → Downloads → **Download Python 3.x** → run installer.
2. ⚠️ **MOST IMPORTANT:** on first screen, TICK ☑️ **"Add python.exe to PATH"** → then **Install Now**.
3. Finish → open **NEW** PowerShell (Start menu → type PowerShell).
4. Type `python --version` → you see `Python 3.10` or higher. ✅
5. Type `pip --version` → you see a version. ✅

**Mac:** python.org → macOS installer → install → terminal → `python3 --version`.

> Forgot the PATH tick? Re-run installer → Modify → tick it. Without PATH, `python` won't work.

---

## 🎉 PHASE 0 DONE — final check

- [ ] Diary has ALL 10 items filled (nothing blank)
- [ ] Telegram bot chat shows /START pressed
- [ ] `python --version` works on laptop

**Now say "Phase 0 done" and we'll start Phase 1 (install bot → first paper run → talk to your AI).** 🚀
