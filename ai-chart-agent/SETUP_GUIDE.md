# Your "Video-Type" AI — Setup Guide (Claude/Gemini + TradingView + Kotak)

Video = Sumedhh, "How To Connect Claude to TradingView" (May 2026).
You get the SAME powers, adapted for NSE swing + Kotak execution + phone control.

## 0. What the video's system does (in 30 seconds)

- **MCP connector** joins AI (Claude Code on laptop) to **TradingView Desktop** — AI reads live chart data, not screenshots.
- You talk in English: "show watchlist", "draw support-resistance on NIFTY", "write Pine Script for gold swing, RR 1:2".
- AI writes Pine Script, **sees its own errors, fixes them**, adds to chart, backtests.
- **Morning brief**: one command scans full watchlist. **rules.json**: your strategy in AI-readable form.
- Honest moment in video: AI-made strategy got **46% accuracy, not 60%** — then he improves it step by step.

## 1. YOUR complete system (better than video — yours actually trades)

```
LAPTOP (analyst brain)              VPS/CLOUD (executor)           PHONE
TradingView Desktop + MCP           kotak-auto-trader bot          Telegram
       ↑                                     ↑                        ↑
Gemini CLI (FREE) or          Kotak Neo API (real orders)     approve ✅ / tasks /
Claude Code (paid)  ──suggest──→  swing 2%/5%/8% + guardian    morning brief ☀️
rules.json = your strategy
```

**Key truth:** the video system does ANALYSIS only — it cannot place Kotak orders.
Your executor bot (already built) does that. AI suggests → you tap ✅ → bot trades.

## 2. Cost options (pick one)

| Path | Cost | Quality |
|---|---|---|
| **A. Gemini CLI (recommended)** — Google's free terminal agent, MCP support, 1000 req/day free | **₹0** | Very good |
| B. Claude Code (exactly like video) | ~$20/month subscription | Best coding |
| TradingView | your FREE account is OK for DAILY charts (swing needs only daily) | — |
| Kotak API + Telegram + brief | ₹0 | — |

Start with Path A. Upgrade to B later only if you want.

## 3. Laptop setup — Path A (FREE, ~30 min)

1. Install **Node.js 18+** (nodejs.org), **Git** (git-scm.com), **TradingView Desktop** (tradingview.com/desktop).
2. Install Gemini CLI:
   ```
   npm install -g @google/gemini-cli
   gemini        (first run: login with your Google account = free tier)
   ```
3. In terminal, go to this folder (`ai-chart-agent`) and paste the **ONE-SHOT prompt** from `MASTER_PROMPT.md` section A. It will: clone the MCP server, install, wire config, launch TradingView in debug mode, health-check, and read your `rules.json`.
4. Test: `Show my watchlist` → `Run the morning brief from MASTER_PROMPT section B`.

Path B (Claude): same steps, but open **Claude Code** instead of `gemini` (needs paid subscription).

## 4. Daily workflow (10 min/day)

1. **8:45 AM** — laptop: `python morning_brief.py` (in kotak-auto-trader) → brief lands on phone. FREE, no AI needed.
2. **9:00 AM** — optional: ask chart-AI the morning-brief prompt (section B) for chart-level view.
3. **3:20 PM** — executor bot auto-scans + enters 70+ setups (paper first!). You get ✅/❌ taps for AI-suggested trades.
4. **Anytime** — phone chat: "buy infy below 1500", "square off all", "my tasks".

## 5. Strategy lab (weekends)

- Paste `PINE_SWING_STRATEGY.pine` into TradingView Pine Editor → Add to chart (1D, NSE stocks) → read Strategy Tester: profit %, win-rate, trades, drawdown.
- Tell AI section D prompts to improve it one change at a time. Keep change only if profit AND win-rate both rise. Max 3 tries per weekend.
- Steal-like-an-artist: any YouTube strategy → NotebookLM doc → section E prompt → Pine + backtest → compare with yours.

## 6. Limits — read before dreaming

- Free TradingView = daily charts fine; some intraday/indicators limited. Swing needs daily only. OK.
- Chart-AI needs **laptop ON + TradingView Desktop open**. Executor bot + phone alerts run on VPS independently.
- MCP is UNOFFICIAL (reads your own desktop app). If TradingView updates break it, wait for repo fix; your Kotak bot keeps running.
- Video's 46%-not-60% lesson: AI strategies need backtesting. Trust numbers, not excitement.
- Paper-trade everything 1 month before real money. Always.

Files here: `rules.json` (strategy) · `MASTER_PROMPT.md` (prompts) · `PINE_SWING_STRATEGY.pine` (ready strategy) · this guide.
Executor: `../kotak-auto-trader/` (bot + `morning_brief.py`).
