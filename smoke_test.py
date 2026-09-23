#!/usr/bin/env python3
"""30-second pre-deploy check. Run it BEFORE you git push:

    python smoke_test.py

It boots the whole app in-process (no network server, no Telegram, no Kotak
orders) and hits every route Render will hit:  HEAD /, /health, /api/status,
/api/positions, /api/tasks, /api/log, POST /start, POST /stop.

Exit code 0 = safe to deploy. Anything else prints what is broken.
Nothing here can place an order: TRADING_MODE is forced to paper and the
Kotak/Telegram keys are forced to dummy values.
"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
TRADER = os.path.join(HERE, "kotak-auto-trader")

# ---- dummy config FIRST: config.py reads the env at import time ----
_TMP = tempfile.mkdtemp(prefix="smoke-state-")
os.environ.update({
    "DATA_DIR": _TMP,
    "TRADING_MODE": "paper",
    "ENABLE_LIVE_ORDERS": "false",
    "BOT_MODE": "swing",
    "BOT_AUTOSTART": "false",          # we start/stop it explicitly below
    "NEO_CONSUMER_KEY": "PASTE_TOKEN_HERE",
    "NEO_MOBILE_NUMBER": "+91XXXXXXXXXX",
    "NEO_UCC": "YOUR_UCC",
    "NEO_MPIN": "123456",
    "NEO_TOTP_SECRET": "PASTE_TOTP_SECRET_HERE",
    "TELEGRAM_BOT_TOKEN": "PASTE_BOT_TOKEN_HERE",
    "TELEGRAM_CHAT_ID": "0",
    "GEMINI_API_KEY": "PASTE_FREE_KEY_HERE",
    "WATCHLIST": "RELIANCE",
})

sys.path.insert(0, TRADER)

FAILS = []


def check(label, fn):
    try:
        fn()
        print(f"  ok   {label}")
    except Exception as e:
        FAILS.append(f"{label}: {type(e).__name__}: {e}")
        print(f"  FAIL {label}: {type(e).__name__}: {e}")


def main():
    print("AI Auto Trader — pre-deploy smoke test")
    print(f"  code dir : {TRADER}")
    print(f"  state dir: {_TMP}")

    def imports():
        import main                      # noqa: F401  (this is where it used to crash)
        import app                       # noqa: F401
    check("import main + app (no Flask/app() clash)", imports)

    import main

    def routes():
        got = {r.path for r in main.web_app.routes}
        for want in ("/", "/health", "/api/status", "/api/positions",
                     "/api/tasks", "/api/log", "/start", "/stop"):
            assert want in got, f"missing route {want}"
    check("all web routes exist", routes)

    def head_ok():
        import inspect
        r = [x for x in main.web_app.routes if getattr(x, "path", "") == "/"]
        assert r and "HEAD" in r[0].methods, "/ must accept HEAD (Render's probe)"
    check("/ accepts HEAD (Render health probe)", head_ok)

    from fastapi.testclient import TestClient
    client = TestClient(main.web_app)

    check("GET  /            -> 200 dashboard",
          lambda: _expect(client.get("/"), 200))
    check("HEAD /            -> 200",
          lambda: _expect(client.head("/"), 200))
    check("GET  /health      -> 200 ok:true",
          lambda: _expect_json(client.get("/health"), 200, ok=True))
    check("GET  /api/status  -> 200",
          lambda: _expect(client.get("/api/status"), 200))
    check("GET  /api/positions -> 200 + list",
          lambda: _positions(client))
    check("GET  /api/tasks   -> 200",
          lambda: _expect(client.get("/api/tasks"), 200))
    check("GET  /api/log     -> 200",
          lambda: _expect(client.get("/api/log?lines=5"), 200))
    check("POST /start       -> bot running",
          lambda: _start(client))
    check("POST /start again -> refused (no double bot)",
          lambda: _start_again(client))
    check("POST /stop        -> bot stopped",
          lambda: _stop(client))

    print()
    if FAILS:
        print("❌ %d check(s) failed — do NOT deploy yet:" % len(FAILS))
        for f in FAILS:
            print("   -", f)
        return 1
    print("✅ All checks passed. Safe to push + deploy.")
    print("   Next: Render → Settings → Start Command = python main.py")
    print("                 Environment → PYTHON_VERSION = 3.12.8")
    return 0


def _expect(resp, code):
    assert resp.status_code == code, f"got HTTP {resp.status_code}"


def _expect_json(resp, code, **kw):
    _expect(resp, code)
    d = resp.json()
    for k, v in kw.items():
        assert d.get(k) == v, f"{k} = {d.get(k)!r}, expected {v!r}"


def _positions(client):
    r = client.get("/api/positions")
    _expect(r, 200)
    d = r.json()
    assert isinstance(d.get("positions"), list), "positions must be a list"
    for p in d["positions"]:
        for k in ("symbol", "qty", "buy_price", "ltp", "pnl"):
            assert k in p, f"position missing key {k}"


def _start(client):
    d = client.post("/start").json()
    assert d.get("ok") is True, d
    import time
    time.sleep(2)
    s = client.get("/api/status").json()
    assert s.get("bot") == "running", s


def _start_again(client):
    d = client.post("/start").json()
    assert d.get("ok") is False, f"double start allowed: {d}"


def _stop(client):
    d = client.post("/stop").json()
    assert d.get("ok") is True, d


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
