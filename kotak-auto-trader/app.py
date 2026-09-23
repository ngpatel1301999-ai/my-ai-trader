"""THIN WRAPPER — the real web app + bot live in main.py.

This file only exists so these keep working:
    python app.py
    uvicorn app:app --host 0.0.0.0 --port $PORT

⚠️ The OLD app.py was a Flask server that launched `python main.py` with
subprocess. On Render that is the wrong shape:
  * `from app import app` in main.py imported the FLASK OBJECT, so `app()`
    raised  TypeError: Flask.__call__() missing 2 required positional
    arguments: 'environ' and 'start_response'   <- the crash you saw.
  * the name `app` was shadowing the bot's `App` class.
  * spawning a second python process on a host that can kill/scale it means
    two bots, two Telegram pollers and duplicated replies.

So: ONE process now. FastAPI serves the dashboard + API, and the trading bot
runs in a daemon thread inside it (see main.py -> start_bot / run_bot_once).
"""
from main import web_app as app      # FastAPI instance ("app" = what uvicorn wants)
from main import serve_web, start_bot, request_stop, bot_state  # noqa: F401

__all__ = ["app", "serve_web", "start_bot", "request_stop", "bot_state"]


if __name__ == "__main__":
    serve_web()
