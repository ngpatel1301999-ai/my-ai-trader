"""Durable state for Render's FREE plan (positions/tasks survive restarts).

WHY: a free Render web service has an EPHEMERAL filesystem. Every deploy or
spin-down wipes the data files, and the bot then reloads whatever stale copy
is in git - freshly bought positions "disappear" from Telegram AND the
dashboard. This module kills that bug for good.

BACKENDS (first one configured wins):
  1. MongoDB Atlas (free M0):  MONGO_URI env  <- recommended, permanent cloud
  2. GitHub contents API:      GH_STATE_TOKEN env (fine-grained PAT)
  none set -> silent no-op, local laptop runs are never touched.

BEHAVIOUR
  * every book save() marks the file dirty; a background thread uploads it
    (debounced ~60s), and SIGTERM / shutdown flushes immediately
  * on boot, if Mongo is configured, the cloud copy is written back over the
    local (freshly wiped) files BEFORE the books are loaded - so what you
    bought yesterday is still there today
  * a SELL removes the position from the stored book (that is the "delete");
    closed trades stay forever in swing_trades (journal / win-rate history)

Env (Render -> Environment):
  MONGO_URI    mongodb+srv://user:pass@cluster0.xxxx.mongodb.net/  (Atlas)
  MONGO_DB     database name (default "trader")
  GH_STATE_TOKEN / GH_STATE_REPO / GH_STATE_BRANCH  (github fallback)
"""
import base64
import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

log = logging.getLogger("state_sync")

LOCK = threading.Lock()
DIRTY = {}        # relpath -> time marked
LAST_OK = {}      # relpath -> time of last successful push
FLUSH_EVERY = 60.0
QUIET = 5.0       # wait a few s after a save before pushing (batch writes)

# files that make up the trading book
STATE_FILES = ["swing_positions.json", "commodity_positions.json",
               "tasks.json", "commodity_tasks.json", "swing_trades.csv",
               "watchlist.json"]

_mongo_client = None


# ---------------- backend selection ----------------
def backend():
    if os.getenv("MONGO_URI", "").strip():
        return "mongo"
    if os.getenv("GH_STATE_TOKEN", "").strip():
        return "github"
    return None


def enabled() -> bool:
    return backend() is not None


def repo() -> str:
    return os.getenv("GH_STATE_REPO", "ngpatel1301999-ai/my-ai-trader").strip()


def branch() -> str:
    return os.getenv("GH_STATE_BRANCH", "main").strip() or "main"


def mark(filename: str):
    """Called by every book save(). Cheap; the flusher thread does the work."""
    if not enabled():
        return
    rel = os.path.basename(filename or "")
    if rel in STATE_FILES:
        with LOCK:
            DIRTY[rel] = time.time()


# ---------------- MongoDB Atlas backend ----------------
def _mongo_db():
    global _mongo_client
    if _mongo_client is None:
        import pymongo
        _mongo_client = pymongo.MongoClient(os.getenv("MONGO_URI").strip(),
                                            serverSelectionTimeoutMS=8000)
        _mongo_client.admin.command("ping")   # fail fast on bad creds/network
    dbn = (os.getenv("MONGO_DB") or "trader").strip()
    return _mongo_client[dbn]


def _coll(rel: str):
    return _mongo_db()[rel.replace(".", "_")]


def _mongo_push(rel: str, text: str) -> bool:
    try:
        _coll(rel).replace_one(
            {"_id": "book"},
            {"_id": "book", "data": text,
             "updated": datetime.now(timezone.utc).isoformat()},
            upsert=True)
        return True
    except Exception as e:
        log.warning("state_sync: mongo push %s failed: %s", rel, e)
        return False


def restore_on_boot():
    """Cloud copy -> local files, BEFORE any book is loaded.
    Mongo is the source of truth while MONGO_URI is set."""
    if backend() != "mongo":
        return
    import paths
    for rel in STATE_FILES:
        try:
            doc = _coll(rel).find_one({"_id": "book"})
            if not doc or not doc.get("data"):
                continue
            with open(paths.data_path(rel), "w") as f:
                f.write(doc["data"])
            log.info("state_sync: restored %s from MongoDB (saved %s)",
                     rel, doc.get("updated", "?"))
        except Exception as e:
            log.warning("state_sync: restore %s failed: %s", rel, e)


# ---------------- GitHub contents-API backend (fallback) ----------------
def _headers() -> dict:
    return {"Authorization": f"Bearer {os.getenv('GH_STATE_TOKEN', '')}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28"}


def _api_url(rel: str) -> str:
    return f"https://api.github.com/repos/{repo()}/contents/kotak-auto-trader/{rel}"


def _req(method: str, url: str, payload=None):
    """stdlib HTTP (no `requests` on Render). Returns (status, body_text)."""
    data = json.dumps(payload).encode() if payload is not None else None
    hdrs = dict(_headers())
    if data is not None:
        hdrs["Content-Type"] = "application/json"
    rq = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(rq, timeout=40) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        try:
            return e.code, e.read().decode("utf-8", "replace")[:300]
        except Exception:
            return e.code, ""
    except Exception as e:
        return 0, str(e)


def _get_sha(rel: str):
    status, body = _req("GET", _api_url(rel) + f"?ref={branch()}")
    if status == 200:
        try:
            return json.loads(body).get("sha")
        except Exception:
            return None
    if status not in (404, 0):
        log.warning("state_sync: sha lookup %s -> HTTP %s %s", rel, status, body[:120])
    return None


def _github_push(rel: str, text: str) -> bool:
    body = {"message": f"state: auto-backup {rel} [bot]",
            "content": base64.b64encode(text.encode()).decode(),
            "branch": branch()}
    sha = _get_sha(rel)
    if sha:
        body["sha"] = sha
    status, txt = _req("PUT", _api_url(rel), body)
    if status in (200, 201):
        return True
    if status == 409:      # someone committed in between - retry once
        sha2 = _get_sha(rel)
        if sha2:
            body["sha"] = sha2
            status, txt = _req("PUT", _api_url(rel), body)
            if status in (200, 201):
                return True
    log.warning("state_sync: push %s -> HTTP %s %s", rel, status, txt[:150])
    return False


# ---------------- shared flush loop ----------------
def push_one(rel: str) -> bool:
    import paths
    fp = paths.data_path(rel)
    if not os.path.exists(fp):
        return False
    with open(fp, "r", errors="replace") as f:
        text = f.read()
    if backend() == "mongo":
        return _mongo_push(rel, text)
    return _github_push(rel, text)


def flush():
    """Push every file whose last save is older than QUIET seconds."""
    if not enabled():
        return
    now = time.time()
    with LOCK:
        due = [k for k, t in DIRTY.items() if now - t >= QUIET]
    for rel in due:
        if push_one(rel):
            with LOCK:
                DIRTY.pop(rel, None)
                LAST_OK[rel] = time.time()
            log.info("state_sync: %s backed up to %s", rel, backend())


def _loop():
    while True:
        time.sleep(FLUSH_EVERY)
        try:
            flush()
        except Exception as e:
            log.warning("state_sync: loop error: %s", e)


def start():
    b = backend()
    if not b:
        log.info("state_sync: no MONGO_URI / GH_STATE_TOKEN - state stays on local "
                 "disk only (Render restarts WILL wipe it).")
        return
    for rel in STATE_FILES:          # back up current book right away
        mark(rel)
    threading.Thread(target=_loop, daemon=True, name="state-sync").start()
    log.info("state_sync: auto-backup ON (backend=%s)", b)
