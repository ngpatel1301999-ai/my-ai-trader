"""Durable state for Render's FREE plan (positions/tasks survive restarts).

WHY: a free Render web service has an EPHEMERAL filesystem. Every deploy or
spin-down wipes the data files, and the bot then reloads the OLD snapshot
that happens to be committed in git - freshly bought positions "disappear"
from Telegram AND the dashboard. That is the bug this module kills.

HOW: after every book save we re-commit the state files to GitHub through
the contents API (fine-grained PAT with Contents: Read and write on this
one repo only). The next deploy / spin-up checks out that commit, so the
book comes back exactly as it was.

Env (Render -> Environment):
  GH_STATE_TOKEN   fine-grained PAT (Contents: Read and write)
  GH_STATE_REPO    owner/repo   (default ngpatel1301999-ai/my-ai-trader)
  GH_STATE_BRANCH  default main
No token set -> silent no-op, so local laptop runs are never touched.
"""
import base64
import logging
import os
import threading
import time

import requests

log = logging.getLogger("state_sync")

LOCK = threading.Lock()
DIRTY = {}        # relpath -> time marked
LAST_OK = {}      # relpath -> time of last successful push
FLUSH_EVERY = 60.0
QUIET = 5.0       # wait a few s after a save before pushing (batch writes)

# files that make up the trading book
STATE_FILES = ["swing_positions.json", "commodity_positions.json",
               "tasks.json", "commodity_tasks.json", "swing_trades.csv"]

_enabled = None


def enabled() -> bool:
    global _enabled
    if _enabled is None:
        _enabled = bool(os.getenv("GH_STATE_TOKEN", "").strip())
    return _enabled


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


def _headers() -> dict:
    return {"Authorization": f"Bearer {os.getenv('GH_STATE_TOKEN', '')}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28"}


def _api_url(rel: str) -> str:
    return f"https://api.github.com/repos/{repo()}/contents/kotak-auto-trader/{rel}"


def _get_sha(rel: str):
    try:
        r = requests.get(_api_url(rel) + f"?ref={branch()}", headers=_headers(), timeout=20)
        if r.status_code == 200:
            return r.json().get("sha")
    except Exception as e:
        log.warning("state_sync: sha lookup %s failed: %s", rel, e)
    return None


def push_one(rel: str) -> bool:
    import paths
    fp = paths.data_path(rel)
    if not os.path.exists(fp):
        return False
    with open(fp, "rb") as f:
        data = f.read()
    body = {"message": f"state: auto-backup {rel} [bot]",
            "content": base64.b64encode(data).decode(),
            "branch": branch()}
    sha = _get_sha(rel)
    if sha:
        body["sha"] = sha
    try:
        r = requests.put(_api_url(rel), headers=_headers(), json=body, timeout=40)
        if r.status_code in (200, 201):
            return True
        if r.status_code == 409:      # someone committed in between - retry once
            sha2 = _get_sha(rel)
            if sha2:
                body["sha"] = sha2
                r = requests.put(_api_url(rel), headers=_headers(), json=body, timeout=40)
                if r.status_code in (200, 201):
                    return True
        log.warning("state_sync: push %s -> HTTP %s %s", rel, r.status_code, r.text[:150])
    except Exception as e:
        log.warning("state_sync: push %s failed: %s", rel, e)
    return False


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
            log.info("state_sync: %s backed up to GitHub", rel)


def _loop():
    while True:
        time.sleep(FLUSH_EVERY)
        try:
            flush()
        except Exception as e:
            log.warning("state_sync: loop error: %s", e)


def start():
    if not enabled():
        log.info("state_sync: no GH_STATE_TOKEN - state stays on local disk only "
                 "(Render restarts WILL wipe it). Add the token in Render -> Environment.")
        return
    # back up the current book immediately, not just on the next trade
    for rel in STATE_FILES:
        mark(rel)
    threading.Thread(target=_loop, daemon=True, name="state-sync").start()
    log.info("state_sync: auto-backup ON -> %s @ %s", repo(), branch())
