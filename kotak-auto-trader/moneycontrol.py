"""Public Moneycontrol extras. NO login, NO password.

News: Google News + article lead (og:description / DDG snippet).
Never dump raw URLs — Telegram auto-links foo.com.
Currency/crypto prices: MC public FX/crypto pages were 503 when checked;
Yahoo is the live/history fallback and is labelled as such.
"""
import logging
import re

import web_tools

log = logging.getLogger("moneycontrol")


def news(query: str, n: int = 5) -> list:
    """Headlines + story text (not links)."""
    q = (query or "").strip() or "markets India"
    hits = web_tools.news_digest(f"{q} site:moneycontrol.com", n) or []
    out = []
    for h in hits:
        title = web_tools.strip_urls(h.get("title") or "")
        if not title:
            continue
        h = dict(h)
        h["title"] = title
        h["src"] = "Moneycontrol"
        h["url"] = ""
        out.append(h)
    return out[:n]


def format_news(hits: list, heading: str = "Moneycontrol") -> str:
    if not hits:
        return f"{heading}: no story text right now."
    lines = [f"{heading} (what the stories say — no login, no links):"]
    for h in hits[:6]:
        title = web_tools.strip_urls(h.get("title") or "")
        title = re.sub(r"\s*[-|]\s*Moneycontrol.*$", "", title, flags=re.I)
        body = web_tools.strip_urls(h.get("body") or "")
        snip = web_tools.strip_urls(h.get("snip") or "")
        if snip.lower() in ("moneycontrol", "google news", "yahoo"):
            snip = ""
        lead = body or snip
        if lead.lower() in title.lower() or lead.lower() in ("moneycontrol",):
            lead = body if body and body.lower() not in title.lower() else ""
        if not title:
            continue
        lines.append(f"• {title[:160]}")
        if lead and lead.lower() not in title.lower():
            lines.append(f"  {lead[:280]}")
    if len(lines) == 1:
        return f"{heading}: no story text right now."
    return "\n".join(lines)
