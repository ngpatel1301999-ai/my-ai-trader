"""KOTAK DOCTOR v10 - same .env names as main.py (NEO_*), verified login.
Run:  python doctor.py
Prints NO secret characters. Paste the whole output.
"""
import hashlib
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from dotenv import load_dotenv
load_dotenv(os.path.join(HERE, ".env"))

EXPECTED_BUILD = "2026-09-17d"


def fp(v: str) -> str:
    return hashlib.sha256(v.encode()).hexdigest()[:8] if v else "-"


def san(o, depth=0):
    if depth > 3:
        return "..."
    if isinstance(o, dict):
        return {k: san(v, depth + 1) for k, v in o.items()}
    if isinstance(o, list):
        return [san(v, depth + 1) for v in o[:5]]
    s = str(o)
    return s if len(s) <= 18 else s[:18] + "...[%d chars]" % len(s)


def env_names(path):
    names = []
    try:
        with open(path, encoding="utf-8-sig") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                names.append(line.split("=", 1)[0].strip())
    except Exception as e:
        return [f"(unreadable: {e})"]
    return names


print("=" * 62)
print("KOTAK DOCTOR v10 - NEO_* names + verified login (no orders)")
print("=" * 62)

import kotak_client as KC
got = getattr(KC, "BUILD", None)
print(f"\n[0] Builds: doctor=v10 kotak_client={got or '?'}")
if got != EXPECTED_BUILD:
    print("!" * 62)
    print("STOP: kotak_client.py is the WRONG version.")
    print(f"  expected BUILD={EXPECTED_BUILD}, got {got!r}")
    print("  You copied doctor.py alone. Extract the FULL zip (see chat).")
    print("!" * 62)
    sys.exit(1)

from config import SETTINGS

env_path = os.path.join(HERE, ".env")
print(f"\n[1] .env: {'FOUND' if os.path.exists(env_path) else 'MISSING!'} at {env_path}")
names = env_names(env_path) if os.path.exists(env_path) else []
print("    keys present (NAMES only, no values):")
print("   ", ", ".join(names) if names else "(none)")
neo = [n for n in names if n.startswith("NEO_")]
kot = [n for n in names if n.startswith("KOTAK_")]
print(f"    NEO_* count={len(neo)}  KOTAK_* count={len(kot)}")
print("    values via config.SETTINGS (same source as main.py):")
for label, v in (("consumer_key", SETTINGS.consumer_key),
                 ("mobile", SETTINGS.mobile_number),
                 ("ucc", SETTINGS.ucc),
                 ("mpin", SETTINGS.mpin),
                 ("totp-secret", SETTINGS.totp_secret)):
    print(f"      {label:12s} present={'YES' if v else 'NO!'} "
          f"len={len(v)} hash={fp(v)}")

import urllib.request
try:
    ip = urllib.request.urlopen("https://api.ipify.org", timeout=10).read().decode()
except Exception as e:
    ip = f"? ({e})"
print(f"\n[2] IP now: {ip}  (Kotak portal whitelist must match EXACTLY)")

real_client = KC.KotakClient(
    SETTINGS.consumer_key, SETTINGS.mobile_number, SETTINGS.ucc,
    SETTINGS.mpin, SETTINGS.totp_secret)

print("\n[3] Login (VERIFIED - checks responses + session tokens)")
ok = real_client.login()
print(f"  -> {'PASS  LOGIN OK' if ok else 'FAIL  ' + real_client.login_error}")
for step, resp in real_client.last_login_resp.items():
    print(f"  {step}: {san(resp)}")
cfg = getattr(real_client.client, "configuration", None)
vt = getattr(cfg, "view_token", None) if cfg else None
et = getattr(cfg, "edit_token", None) if cfg else None
print(f"  session: view_token={'len ' + str(len(vt)) if vt else 'MISSING'} "
      f"edit_token={'len ' + str(len(et)) if et else 'MISSING'}")

if ok:
    print("\n[4] History WITH session (RELIANCE daily)")
    try:
        h = real_client.daily_history("2885", days=8)
        print(f"  candles: {len(h)} last close: {h[-1]['c'] if h else '-'}"
              f"  -> {'PASS' if h else 'FAIL'}")
    except Exception as e:
        print("  FAIL:", str(e)[:300])

    print("\n[5] Quotes (raw, WITH session)")
    try:
        r = real_client._plain_client().quotes(
            instrument_tokens=[{"instrument_token": "2885",
                                "exchange_segment": "nse_cm"}],
            quote_type="all")
        s = str(r)
        print("  reply:", s[:300], "->",
              "PASS" if "2885" in s and "error" not in s.lower() else "FAIL")
    except Exception as e:
        print("  FAIL:", str(e)[:300])

    print("\n[6] Margin test (1 RELIANCE MIS - calculation ONLY, no order)")
    try:
        m = real_client._plain_client().margin_required(
            exchange_segment="nse_cm", price="1300", order_type="L",
            product="MIS", quantity="1", instrument_token="2885",
            transaction_type="B")
        bad = isinstance(m, dict) and (
            "error" in str(m).lower() or "Error Message" in m)
        print("  -> " + (("FAIL  " + str(m)[:250]) if bad
                         else ("PASS  trading path alive: " + str(m)[:250])))
    except Exception as e:
        print("  FAIL:", str(e)[:300])
else:
    print("\n[4][5][6] SKIPPED - no session. Fix login first, then re-run.")

print("\n[7] Saved tokens on file")
import json
vf = os.path.join(HERE, "tokens_verified.json")
if os.path.exists(vf):
    d = json.load(open(vf))
    print(f"  {len(d)} tokens: " + ", ".join(sorted(d)))
else:
    print("  tokens_verified.json MISSING")

print("\n" + "=" * 62)
print("Paste ALL output here. Numbers/hashes cannot reconstruct secrets.")
print("=" * 62)
