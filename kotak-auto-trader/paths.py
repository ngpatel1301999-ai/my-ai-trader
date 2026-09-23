"""Where the bot keeps its state files.

On a laptop this is just the project folder (current working directory), so
nothing changes for you.

On Render / Heroku / Fly the disk is EPHEMERAL: every deploy or restart wipes
tasks.json, swing_positions.json, swing_trades.csv, memory.json ...
Fix without touching the code:

  1. Render dashboard -> your service -> Disks -> Add disk
       Mount path: /var/data      Size: 1 GB (minimum)
  2. Environment -> add:  DATA_DIR=/var/data

Now every state file lives on the disk and survives deploys/restarts.
"""
import os

_DIR = None


def data_dir() -> str:
    """Absolute folder for state files. DATA_DIR env var wins, else cwd."""
    global _DIR
    if _DIR is None:
        d = os.getenv("DATA_DIR", "").strip() or os.getcwd()
        d = os.path.abspath(os.path.expanduser(d))
        try:
            os.makedirs(d, exist_ok=True)
        except OSError:
            d = os.getcwd()          # unwritable mount -> fall back, never crash
        _DIR = d
    return _DIR


def data_path(name: str) -> str:
    """Full path of a state file inside data_dir()."""
    return os.path.join(data_dir(), name)
