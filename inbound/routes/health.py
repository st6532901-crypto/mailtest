"""GET /api/health - the app is up, and is the Resend configuration present?

Never fails because of storage (there is none) and never reveals secret values.
"""

from __future__ import annotations

from fastapi import APIRouter

from inbound.config import get_settings

router = APIRouter()


@router.get("/api/health", tags=["meta"])
async def health() -> dict:
    settings = get_settings()
    webhook_ready = bool(settings.resend_webhook_secret)
    api_ready = bool(settings.resend_api_key)
    return {
        "status": "ok",
        "app": "running",
        "storage": "none (temporary in-memory cache only; mail is read from Resend)",
        "resend": {
            "webhook_secret_configured": webhook_ready,  # required: verifies incoming webhooks
            "api_key_configured": api_ready,             # needed for a reliable dashboard on Vercel
        },
        "ready_to_receive": webhook_ready,
        "dashboard_is_reliable_on_serverless": api_ready,
    }
