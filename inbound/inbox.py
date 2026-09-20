"""Builds the list the dashboard shows.

Sources, merged and de-duplicated by ``email_id``:

1. Resend's Receiving API (durable, shared by every serverless instance).
   Used only when RESEND_API_KEY is set.
2. The in-memory store filled by the webhook (fast, but per-instance and lost
   on restart).

Nothing is written to disk or to any database.
"""

from __future__ import annotations

import logging
import threading
import time

from inbound.config import get_settings
from inbound.resend_client import ResendApiError, list_received_emails
from inbound.schemas import EmailOut, SourceStatus
from inbound.store import MAX_EMAILS, email_store

logger = logging.getLogger("inbound.inbox")

# Resend rate-limits its API (a few requests/second per team). Several dashboards
# polling every 5 s stay far below that, but a short cache costs nothing.
CACHE_TTL_SECONDS = 3.0

_cache_lock = threading.Lock()
_cache: tuple[float, list[EmailOut]] | None = None


def reset_cache() -> None:
    global _cache
    with _cache_lock:
        _cache = None


def _fetch_from_resend(api_key: str) -> list[EmailOut]:
    global _cache
    now = time.monotonic()
    with _cache_lock:
        if _cache and now - _cache[0] < CACHE_TTL_SECONDS:
            return _cache[1]

    emails = [EmailOut.from_data(d) for d in list_received_emails(api_key, MAX_EMAILS)]
    with _cache_lock:
        _cache = (time.monotonic(), emails)
    return emails


def collect_emails(limit: int) -> tuple[list[EmailOut], SourceStatus]:
    settings = get_settings()

    api_emails: list[EmailOut] = []
    detail: str | None = None
    if not settings.resend_api_key:
        state = "not_configured"
    else:
        try:
            api_emails = _fetch_from_resend(settings.resend_api_key)
            state = "ok"
        except ResendApiError as exc:
            state, detail = "error", str(exc)
            logger.warning("Resend API read failed: %s", exc)
        except Exception:  # never let the dashboard die because of the API read
            state, detail = "error", "Unexpected error reading the Resend API"
            logger.exception("Unexpected error reading the Resend API")

    merged = {e.email_id: e for e in email_store.latest(MAX_EMAILS)}
    merged.update({e.email_id: e for e in api_emails})  # Resend's copy wins
    emails = sorted(merged.values(), key=lambda e: (e.received_at, e.email_id), reverse=True)[:limit]

    return emails, SourceStatus(resend_api=state, resend_api_detail=detail, memory_count=len(email_store))
