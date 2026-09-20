"""POST /api/webhook/resend - receives Resend ``email.received`` events."""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import ValidationError

from inbound.config import get_settings
from inbound.schemas import EmailOut, ReceivedEmailData, ResendEvent, WebhookAck
from inbound.security import (
    WebhookSecretError,
    WebhookVerificationError,
    get_message_id,
    verify_webhook,
)
from inbound.store import email_store

logger = logging.getLogger("inbound.webhook")
router = APIRouter()

MAX_BODY_BYTES = 1_000_000  # Resend sends metadata only; anything huge is not from Resend.
EVENT_EMAIL_RECEIVED = "email.received"


@router.post("/api/webhook/resend", response_model=WebhookAck, tags=["webhook"])
async def resend_webhook(request: Request) -> WebhookAck:
    settings = get_settings()
    delivery_id = get_message_id(request.headers)

    # 1. RAW body first. Signature verification needs the exact bytes.
    raw_body = await request.body()
    if len(raw_body) > MAX_BODY_BYTES:
        logger.warning("Webhook rejected: body too large (%d bytes) id=%s", len(raw_body), delivery_id)
        raise HTTPException(status_code=413, detail="Payload too large")

    # 2. Authenticate.
    if not settings.resend_webhook_secret:
        logger.error("RESEND_WEBHOOK_SECRET is not configured; cannot verify webhooks")
        raise HTTPException(status_code=500, detail="Webhook receiver is not configured")

    try:
        verify_webhook(
            raw_body,
            request.headers,
            settings.resend_webhook_secret,
            tolerance_seconds=settings.webhook_tolerance_seconds,
        )
    except WebhookVerificationError as exc:
        logger.warning("Webhook rejected: %s (id=%s)", exc, delivery_id)
        raise HTTPException(status_code=400, detail="Invalid webhook signature") from exc
    except WebhookSecretError as exc:
        logger.error("Webhook secret is misconfigured: %s", exc)
        raise HTTPException(status_code=500, detail="Webhook receiver is not configured") from exc

    # 3. Parse + validate (only after the signature is proven).
    try:
        raw_event = json.loads(raw_body)
        event = ResendEvent.model_validate(raw_event)
    except (ValueError, ValidationError) as exc:
        logger.error("Webhook has a valid signature but an invalid body (id=%s): %s", delivery_id, exc)
        raise HTTPException(status_code=400, detail="Invalid webhook payload") from exc

    # Resend can be configured to send other event types to the same URL.
    # Acknowledge them with 200 so they are not retried.
    if event.type != EVENT_EMAIL_RECEIVED:
        logger.info("Ignoring event type=%s id=%s", event.type, delivery_id)
        return WebhookAck(status="ignored", event_type=event.type)

    try:
        email = ReceivedEmailData.model_validate(event.data)
    except ValidationError as exc:
        logger.error(
            "email.received payload failed validation (id=%s): %s",
            delivery_id,
            exc.errors(include_input=False, include_url=False),
        )
        raise HTTPException(status_code=400, detail="Invalid email.received payload") from exc

    # 4. Remember it (in memory only; see inbound/store.py). Resend itself keeps the
    #    durable copy, which the dashboard reads through the Receiving API.
    if email_store.add(EmailOut.from_data(email)):
        logger.info("Received inbound email email_id=%s delivery=%s", email.email_id, delivery_id)
        return WebhookAck(status="accepted", email_id=email.email_id)

    logger.info("Duplicate delivery ignored email_id=%s delivery=%s", email.email_id, delivery_id)
    return WebhookAck(status="duplicate", email_id=email.email_id)
