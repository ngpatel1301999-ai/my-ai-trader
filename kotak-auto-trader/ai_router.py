"""Multi-AI router: 28 AI slots, newest models auto-found.
- chat via ordered fallback chain (free providers first)
- FAST: 8s timeout + skip a provider for 8 min after it fails (no more 2-min waits)
- auto_update_all() / consensus() / do_self_update()
Stdlib only. No key = provider skipped.
"""
import json
import logging
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

log = logging.getLogger("router")

MODELS_FILE = "ai_models.json"
CALL_TIMEOUT = 8          # seconds — was 30, that made Telegram feel hung
DEAD_FOR = 8 * 60         # skip a failed provider this long
_dead_until = {}          # provider -> unix time

# type: gemini | anthropic | oai (OpenAI-compatible chat completions)
# no_key: needs no key. local_only: only used if listed in AI_PROVIDERS.
PROVIDERS = {
    "gemini": {"type": "gemini", "key_env": "GEMINI_API_KEY", "default": "gemini-2.5-flash"},
    "groq": {"type": "oai", "base": "https://api.groq.com/openai/v1",
             "key_env": "GROQ_API_KEY", "default": "llama-3.3-70b-versatile"},
    "cerebras": {"type": "oai", "base": "https://api.cerebras.ai/v1",
                 "key_env": "CEREBRAS_API_KEY", "default": "llama-3.3-70b"},
    "openrouter": {"type": "oai", "base": "https://openrouter.ai/api/v1",
                   "key_env": "OPENROUTER_API_KEY", "default": "meta-llama/llama-3.3-70b-instruct:free"},
    "together": {"type": "oai", "base": "https://api.together.xyz/v1",
                 "key_env": "TOGETHER_API_KEY", "default": "meta-llama/Llama-3.3-70B-Instruct-Turbo-Free"},
    "fireworks": {"type": "oai", "base": "https://api.fireworks.ai/inference/v1",
                  "key_env": "FIREWORKS_API_KEY", "default": "accounts/fireworks/models/llama-v3p1-8b-instruct"},
    "sambanova": {"type": "oai", "base": "https://api.sambanova.ai/v1",
                  "key_env": "SAMBANOVA_API_KEY", "default": "Meta-Llama-3.3-70B-Instruct"},
    "hyperbolic": {"type": "oai", "base": "https://api.hyperbolic.xyz/v1",
                   "key_env": "HYPERBOLIC_API_KEY", "default": "meta-llama/Meta-Llama-3-70B-Instruct"},
    "huggingface": {"type": "oai", "base": "https://router.huggingface.co/v1",
                    "key_env": "HF_TOKEN", "default": "meta-llama/Llama-3.3-70B-Instruct"},
    "github_models": {"type": "oai", "base": "https://models.github.ai/inference",
                      "key_env": "GITHUB_TOKEN", "default": "openai/gpt-4o-mini"},
    "nvidia": {"type": "oai", "base": "https://integrate.api.nvidia.com/v1",
               "key_env": "NVIDIA_API_KEY", "default": "meta/llama-3.3-70b-instruct"},
    "nebius": {"type": "oai", "base": "https://api.studio.nebius.ai/v1",
               "key_env": "NEBIUS_API_KEY", "default": "meta-llama/Meta-Llama-3.1-70B-Instruct"},
    "zhipu": {"type": "oai", "base": "https://open.bigmodel.cn/api/paas/v4",
              "key_env": "ZHIPU_API_KEY", "default": "glm-4-flash"},
    "qwen": {"type": "oai", "base": "https://dashscope.aliyuncs.com/compatible-mode/v1",
             "key_env": "DASHSCOPE_API_KEY", "default": "qwen-turbo"},
    "siliconflow": {"type": "oai", "base": "https://api.siliconflow.cn/v1",
                    "key_env": "SILICONFLOW_API_KEY", "default": "Qwen/Qwen2.5-7B-Instruct"},
    "cohere": {"type": "oai", "base": "https://api.cohere.ai/compatibility/v1",
               "key_env": "COHERE_API_KEY", "default": "command-a-03-2025"},
    "deepseek": {"type": "oai", "base": "https://api.deepseek.com/v1",
                 "key_env": "DEEPSEEK_API_KEY", "default": "deepseek-chat"},
    "perplexity": {"type": "oai", "base": "https://api.perplexity.ai",
                   "key_env": "PERPLEXITY_API_KEY", "default": "sonar"},
    "openai": {"type": "oai", "base": "https://api.openai.com/v1",
               "key_env": "OPENAI_API_KEY", "default": "gpt-4o-mini"},
    "xai": {"type": "oai", "base": "https://api.x.ai/v1",
            "key_env": "XAI_API_KEY", "default": "grok-3-mini"},
    "mistral": {"type": "oai", "base": "https://api.mistral.ai/v1",
                "key_env": "MISTRAL_API_KEY", "default": "mistral-small-latest"},
    "moonshot": {"type": "oai", "base": "https://api.moonshot.ai/v1",
                 "key_env": "MOONSHOT_API_KEY", "default": "kimi-k2-0711-preview"},
    "anthropic": {"type": "anthropic", "base": "https://api.anthropic.com/v1",
                  "key_env": "ANTHROPIC_API_KEY", "default": "claude-sonnet-4-5"},
    "ollama": {"type": "oai", "base": "http://localhost:11434/v1", "no_key": True,
               "local_only": True, "key_env": "", "default": "llama3.1:8b"},
    "lmstudio": {"type": "oai", "base": "http://localhost:1234/v1", "no_key": True,
                 "local_only": True, "key_env": "", "default": "local-model"},
    "pollinations": {"type": "oai", "base": "https://text.pollinations.ai/openai",
                     "no_key": True, "key_env": "", "default": "openai"},
    "custom1": {"type": "oai", "base_env": "CUSTOM1_BASE", "key_env": "CUSTOM1_KEY",
                "model_env": "CUSTOM1_MODEL"},
    "custom2": {"type": "oai", "base_env": "CUSTOM2_BASE", "key_env": "CUSTOM2_KEY",
                "model_env": "CUSTOM2_MODEL"},
}

# Try saved model first, then these. Cap at 3 attempts per call.
GEMINI_FALLBACKS = [
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-3.5-flash-lite",
    "gemini-3.5-flash",
    "gemini-2.0-flash",
]
BAD_MODEL_BITS = ("embed", "whisper", "tts", "moderation", "guard",
                  "image", "audio", "realtime", "codex", "search", "rerank")


def _extract_json(text: str):
    try:
        return json.loads(text)
    except Exception:
        pass
    m = re.search(r"\{.*\}", text, re.S)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            pass
    return None


def _post(url, payload, headers, timeout=CALL_TIMEOUT):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        body = e.read()[:300].decode("utf-8", "ignore")
        raise RuntimeError(f"HTTP {e.code} {body}") from e


def _get(url, headers, timeout=12):
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        body = e.read()[:300].decode("utf-8", "ignore")
        raise RuntimeError(f"HTTP {e.code} {body}") from e


def _mark_dead(prov: str, why: str):
    _dead_until[prov] = time.time() + DEAD_FOR
    log.warning("provider %s marked dead %ds: %s", prov, DEAD_FOR, str(why)[:160])


def _is_dead(prov: str) -> bool:
    return time.time() < _dead_until.get(prov, 0)


# ---------------- raw provider calls (return TEXT) ----------------
def _gemini_text(key, model, system, user):
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{model}:generateContent?key={key}")
    payload = {
        "system_instruction": {"parts": [{"text": system}]},
        "contents": [{"parts": [{"text": user}]}],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 1500},
    }
    try:
        d = _post(url, payload, {"Content-Type": "application/json"})
    except Exception:
        # older models reject system_instruction — fold it into the user turn
        payload = {
            "contents": [{"parts": [{"text": system + "\n\n" + user}]}],
            "generationConfig": {"temperature": 0.2, "maxOutputTokens": 1500},
        }
        d = _post(url, payload, {"Content-Type": "application/json"})
    return d["candidates"][0]["content"]["parts"][0]["text"]


def _oai_text(base, key, model, system, user, extra_headers=None):
    h = {"Content-Type": "application/json"}
    if key:
        h["Authorization"] = f"Bearer {key}"
    if extra_headers:
        h.update(extra_headers)
    d = _post(f"{base}/chat/completions",
              {"model": model, "temperature": 0.2, "max_tokens": 1500,
               "messages": [{"role": "system", "content": system},
                            {"role": "user", "content": user}]}, h)
    return d["choices"][0]["message"]["content"]


def _anthropic_text(key, model, system, user):
    d = _post("https://api.anthropic.com/v1/messages",
              {"model": model, "max_tokens": 1500, "system": system,
               "messages": [{"role": "user", "content": user}]},
              {"Content-Type": "application/json", "x-api-key": key,
               "anthropic-version": "2023-06-01"})
    return "".join(b.get("text", "") for b in d.get("content", []))


def load_models() -> dict:
    try:
        if os.path.exists(MODELS_FILE):
            return json.load(open(MODELS_FILE)) or {}
    except Exception:
        pass
    return {}


def save_models(m: dict):
    try:
        json.dump(m, open(MODELS_FILE, "w"), indent=1)
    except Exception as e:
        log.warning("models save: %s", e)


def base_for(provider: str) -> str:
    p = PROVIDERS[provider]
    if "base" in p:
        return p["base"]
    return os.getenv(p.get("base_env", ""), "").strip().rstrip("/")


def key_for(provider: str) -> str:
    p = PROVIDERS[provider]
    if p.get("no_key"):
        return "ok"
    if "base_env" in p and not base_for(provider):
        return ""
    k = os.getenv(p.get("key_env", ""), "").strip()
    return "" if (not k or "PASTE" in k) else k


def model_for(provider: str) -> str:
    saved = load_models()
    if saved.get(provider):
        return saved[provider]
    p = PROVIDERS[provider]
    if "model_env" in p:
        return os.getenv(p["model_env"], "").strip() or "default"
    return p["default"]


def provider_order() -> list:
    raw = os.getenv("AI_PROVIDERS", "gemini,groq,cerebras,openrouter")
    order = [p.strip().lower() for p in raw.split(",") if p.strip().lower() in PROVIDERS]
    # auto-enable: any provider with a real key joins. Do NOT auto-add
    # no_key toys (pollinations) — they were adding 30s of hang per message.
    for p in PROVIDERS:
        if p in order or PROVIDERS[p].get("local_only") or PROVIDERS[p].get("no_key"):
            continue
        if key_for(p):
            order.append(p)
    return order or ["gemini"]


def chat_text(provider: str, system: str, user: str) -> str:
    """Single provider, single model. Raises on failure."""
    p = PROVIDERS[provider]
    key = key_for(provider)
    if not key:
        raise RuntimeError("no key")
    real_key = "" if key == "ok" else key
    if p["type"] == "gemini":
        saved = load_models().get("gemini")
        try_models = []
        if saved:
            try_models.append(saved)
        for fb in GEMINI_FALLBACKS:
            if fb not in try_models:
                try_models.append(fb)
        last_err = None
        for m in try_models[:3]:
            try:
                txt = _gemini_text(real_key, m, system, user)
                if m != saved:
                    s = load_models()
                    s["gemini"] = m
                    save_models(s)
                    log.info("gemini working model cached: %s", m)
                return txt
            except Exception as e:
                last_err = e
                log.warning("gemini model %s failed: %s", m, str(e)[:120])
        raise last_err or RuntimeError("gemini failed")
    if p["type"] == "anthropic":
        return _anthropic_text(real_key, model_for(provider), system, user)
    extra = {"HTTP-Referer": "https://localhost", "X-Title": "kotak-bot"} \
        if provider == "openrouter" else None
    return _oai_text(base_for(provider), real_key, model_for(provider),
                     system, user, extra)


def _live_providers():
    for prov in provider_order():
        if not key_for(prov) or _is_dead(prov):
            continue
        yield prov


def ask_json(system: str, user: str) -> dict | None:
    """Try providers in order until one returns valid JSON."""
    for prov in _live_providers():
        try:
            out = _extract_json(chat_text(prov, system, user))
            if isinstance(out, dict):
                return out
            # HTTP worked but not JSON — don't kill the provider, just skip
            log.warning("provider %s returned non-JSON", prov)
        except Exception as e:
            _mark_dead(prov, e)
    return None


def ask_text(user: str, system: str = "You are a helpful trading assistant. Be precise and short.") -> str:
    for prov in _live_providers():
        try:
            txt = chat_text(prov, system, user)
            if txt and txt.strip():
                return txt.strip()
        except Exception as e:
            _mark_dead(prov, e)
    return ""


def consensus(question: str, context: str = "", max_minds: int = 3) -> str:
    """Ask up to 3 different AIs, merge into ONE precise answer."""
    answers = []
    for prov in _live_providers():
        if len(answers) >= max_minds:
            break
        if PROVIDERS[prov].get("local_only"):
            continue
        try:
            a = chat_text(prov, "Answer precisely in under 120 words. No fluff.",
                          f"{context}\n\nQ: {question}" if context else question)
            if a.strip():
                answers.append((prov, a.strip()[:1200]))
        except Exception as e:
            _mark_dead(prov, e)
    if not answers:
        return ""
    if len(answers) == 1:
        return f"🧠 ({answers[0][0]}):\n{answers[0][1]}"
    blob = "\n\n".join(f"[{p}]: {a}" for p, a in answers)
    merged = ask_text(f"Merge these {len(answers)} AI answers into ONE precise answer "
                      f"(under 150 words). Start with the conclusion. Note disagreement if any.\n\n{blob}",
                      "You merge AI answers precisely.")
    minds = ", ".join(p for p, _ in answers)
    return f"🧠🧠 Consensus of {minds}:\n{(merged or answers[0][1])[:1400]}"


# ---------------- self-update: latest models ----------------
def _pick_latest(ids: list) -> str:
    cands = [i for i in ids if not any(b in i.lower() for b in BAD_MODEL_BITS)]
    if not cands:
        return ""

    def score(i: str):
        l = i.lower()
        s = 0
        if "instruct" in l or "chat" in l:
            s += 3
        if "free" in l:
            s += 1
        nums = re.findall(r"(\d+)(?:\.(\d+))?", l)
        if nums:
            try:
                s += int(nums[-1][0]) * 0.1 + int(nums[-1][1] or 0) * 0.01
            except ValueError:
                pass
        if "preview" in l or "latest" in l:
            s += 0.5
        return s
    cands.sort(key=score, reverse=True)
    return cands[0]


def auto_update_all() -> str:
    """Fetch /models per provider, keep newest chat model. Returns report."""
    saved = load_models()
    lines = []
    for prov in PROVIDERS:
        key = key_for(prov)
        if not key:
            lines.append(f"· {prov}: skipped (no key in .env)")
            continue
        try:
            p = PROVIDERS[prov]
            real_key = "" if key == "ok" else key
            if p["type"] == "gemini":
                d = _get(f"https://generativelanguage.googleapis.com/v1beta/models?key={real_key}", {})
                ids = [m.get("name", "").split("/")[-1] for m in d.get("models", [])]
                ids = [i for i in ids if "gemini" in i and "embed" not in i]
            elif p["type"] == "anthropic":
                d = _get("https://api.anthropic.com/v1/models",
                         {"x-api-key": real_key, "anthropic-version": "2023-06-01"})
                ids = [m.get("id", "") for m in d.get("data", [])]
            else:
                h = {"Authorization": f"Bearer {real_key}"} if real_key else {}
                d = _get(f"{base_for(prov)}/models", h)
                ids = [m.get("id", "") for m in d.get("data", [])]
            ids = [i for i in ids if i]
            if not ids:
                lines.append(f"· {prov}: no models listed")
                continue
            best = _pick_latest(ids)
            old = saved.get(prov, model_for(prov))
            saved[prov] = best or old
            mark = "🆙" if best and best != old else "="
            lines.append(f"{mark} {prov}: {old} -> {saved[prov]}")
        except Exception as e:
            lines.append(f"· {prov}: update failed ({str(e)[:60]})")
    save_models(saved)
    return "🤖 AI MODELS UPDATE:\n" + "\n".join(lines)


def status_report() -> str:
    saved = load_models()
    lines = []
    for prov in provider_order():
        p = PROVIDERS[prov]
        mark = "🆓" if p.get("no_key") else ("🔑" if key_for(prov) else "—")
        dead = " (cooling)" if _is_dead(prov) else ""
        lines.append(f"{mark} {prov}: {saved.get(prov, model_for(prov))}{dead}")
    return f"🧠 AI brain chain:\n" + "\n".join(lines)


def do_self_update() -> str:
    """git pull + pip install + restart process. Returns only on failure."""
    steps = []
    try:
        if os.path.isdir(".git"):
            r = subprocess.run(["git", "pull"], capture_output=True, text=True, timeout=90)
            steps.append("git: " + (r.stdout.strip() or r.stderr.strip() or "ok")[:120])
        else:
            steps.append("git: not a repo, skipped")
        r = subprocess.run([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"],
                           capture_output=True, text=True, timeout=300)
        steps.append("pip: " + ("ok" if r.returncode == 0 else r.stderr.strip()[:120]))
    except Exception as e:
        return "Self-update failed: " + str(e)[:200]
    log.warning("SELF-UPDATE restarting: %s", steps)
    try:
        with open("update_note.txt", "w") as f:
            f.write("Updated and restarted.\n" + "\n".join(steps))
    except Exception:
        pass
    os.execv(sys.executable, [sys.executable, "main.py"])
    return "restarting..."  # never reached
