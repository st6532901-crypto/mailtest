"""Environment-driven configuration.

Secrets are only ever read from the environment (or a local, git-ignored
``.env`` file). Nothing here is hard-coded and nothing is logged.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from functools import lru_cache

from dotenv import load_dotenv

# Loads ./.env for local development. Real environment variables (Vercel) always
# win because override=False, and on Vercel there is no .env file anyway.
load_dotenv(override=False)


@dataclass(frozen=True)
class Settings:
    resend_webhook_secret: str | None
    resend_api_key: str | None
    log_level: str
    webhook_tolerance_seconds: int


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings(
        resend_webhook_secret=(os.getenv("RESEND_WEBHOOK_SECRET") or "").strip() or None,
        resend_api_key=(os.getenv("RESEND_API_KEY") or "").strip() or None,
        log_level=(os.getenv("LOG_LEVEL") or "INFO").strip().upper(),
        webhook_tolerance_seconds=_int_env("WEBHOOK_TOLERANCE_SECONDS", 300),
    )


def configure_logging() -> None:
    """Log to stdout/stderr, which Vercel captures in the Runtime Logs."""
    level = getattr(logging, get_settings().log_level, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("inbound").setLevel(level)
