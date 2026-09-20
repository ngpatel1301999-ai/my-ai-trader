# Master Prompts — paste into Claude Code or Gemini CLI (like the video's one-shot)

## A. ONE-SHOT SETUP (paste once, it does everything)

```
I want to connect you to my TradingView Desktop app via MCP.
Do all steps yourself, ask me only if blocked:

1. Check node (18+), git are installed. If not, tell me exact install commands for my OS.
2. Clone https://github.com/tradesdontlie/tradingview-mcp.git into ./tradingview-mcp and run npm install.
3. Add it to my MCP config as server name "tradingview"
   (command: node, args: [<full-path>/tradingview-mcp/src/server.js]).
4. Launch my TradingView Desktop app with remote debugging port 9222
   (auto-detect install path; ask me if you can't find it).
5. Verify with tv_health_check and show me the result.
6. Then read ./rules.json (my swing strategy) and confirm you understood it in 5 bullet points.

My OS: <WINDOWS/MAC>. Go step by step.
```

## B. DAILY MORNING BRIEF (every day ~9:00 AM)

```
Load rules.json. Scan my full watchlist on 1D timeframe.
For EACH stock give ONE line: score/100, distance to 20-day high, above/below EMA50, volume x, RSI, verdict (✅/👀/❌).
Then TOP 3 candidates table with entry, SL (-2%), T1 (+5%), T2 (+8%).
End with: market risk note (NIFTY above/below its EMA50?).
```

## C. LEVELS ON CHART (like video: support/resistance)

```
On NSE:RELIANCE 1D: read last 6 months, find 3 support + 3 resistance zones,
draw them with lines + short labels explaining WHY each matters.
```

## D. PINE STRATEGY LOOP (write → backtest → improve)

First time:
```
Write a Pine v5 STRATEGY for my rules.json (20-day breakout + EMA50 trend + volume filter,
SL 2%, T1 5% half-out + breakeven, T2 8%, 10-bar time stop).
Inject it, compile, fix ALL errors yourself, add to chart on 1D, and report:
net profit %, win-rate %, no. of trades, max drawdown %.
```

Improve loop (repeat 2-3 times max):
```
Win-rate is only X%. Look at losing trades on the chart.
Try ONE change at a time (RSI filter / ADX>20 / ATR-based stop / volume 1.5x),
recompile, re-test, keep the change ONLY if profit AND win-rate both improve.
Show before/after table. Stop after 3 tries.
```

## E. COPY ANY YOUTUBER'S STRATEGY (video's NotebookLM trick)

1. YouTube → copy that trader's strategy videos → NotebookLM → "Create notebook" → paste links
2. Ask NotebookLM: "Write the complete entry/exit/risk rules as a numbered document"
3. Paste that document here and say:
```
Convert this into a Pine v5 strategy + backtest it on NSE:RELIANCE 1D.
Report profit %, win-rate, trades, drawdown. Then compare vs my rules.json strategy.
```

## F. SAFETY LINE (say once per new chat)

```
Rules: suggest-only, no real orders. NSE daily charts. Never promise profit/accuracy.
If data looks weak, say AVOID instead of forcing a trade.
```
