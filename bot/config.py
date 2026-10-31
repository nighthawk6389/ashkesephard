"""Settings for the recipe email bot, read from environment variables (GitHub Actions secrets)."""
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def parse_family(raw):
    """FAMILY_SENDERS is either JSON ({"orlee@example.com": "Orlee"}) or one "Name <email>" per line."""
    raw = (raw or "").strip()
    if not raw:
        return {}
    if raw.startswith("{"):
        return {k.strip().lower(): v.strip() for k, v in json.loads(raw).items()}
    family = {}
    for line in raw.splitlines():
        m = re.match(r"\s*(.+?)\s*<\s*([^>\s]+@[^>\s]+)\s*>\s*$", line)
        if m:
            family[m.group(2).lower()] = m.group(1)
        elif line.strip():
            raise ValueError(f"FAMILY_SENDERS line should look like 'Orlee <orlee@example.com>': {line!r}")
    return family


@dataclass
class Settings:
    bot_address: str = ""
    app_password: str = ""
    imap_host: str = "imap.gmail.com"
    imap_port: int = 993
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 465
    site_url: str = ""
    admin_email: str = ""
    model: str = "claude-opus-5-5"
    gateway_key: str = ""  # Vercel AI Gateway; used instead of ANTHROPIC_API_KEY when set
    family: dict = field(default_factory=dict)
    max_per_run: int = 15

    @classmethod
    def from_env(cls):
        env = os.environ
        return cls(
            bot_address=env.get("BOT_EMAIL_ADDRESS", "").strip(),
            app_password=env.get("BOT_EMAIL_APP_PASSWORD", "").replace(" ", ""),
            imap_host=env.get("IMAP_HOST") or "imap.gmail.com",
            imap_port=int(env.get("IMAP_PORT") or 993),
            smtp_host=env.get("SMTP_HOST") or "smtp.gmail.com",
            smtp_port=int(env.get("SMTP_PORT") or 465),
            site_url=(env.get("SITE_URL") or "").rstrip("/"),
            admin_email=env.get("ADMIN_EMAIL", "").strip().lower(),
            model=env.get("BOT_MODEL") or "claude-opus-5-5",
            gateway_key=env.get("AI_GATEWAY_API_KEY", "").strip(),
            family=parse_family(env.get("FAMILY_SENDERS")),
            max_per_run=int(env.get("BOT_MAX_PER_RUN") or 15),
        )

    def missing(self):
        needed = {"BOT_EMAIL_ADDRESS": self.bot_address, "BOT_EMAIL_APP_PASSWORD": self.app_password,
                  "SITE_URL": self.site_url, "FAMILY_SENDERS": self.family,
                  "ANTHROPIC_API_KEY or AI_GATEWAY_API_KEY": self.gateway_key or os.environ.get("ANTHROPIC_API_KEY")}
        return [name for name, value in needed.items() if not value]

    def recipe_url(self, slug):
        return f"{self.site_url}/?recipe={slug}"
