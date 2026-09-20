"""Resend (Svix / Standard Webhooks) signature verification.

Deliberately dependency-free (standard library only) so it is easy to audit
and unit-test.

Resend signs every webhook with three headers:

    svix-id         unique message id (identical on retries of the same event)
    svix-timestamp  unix seconds when this delivery attempt was sent
    svix-signature  space separated list of "v1,<base64 HMAC-SHA256>"

The signature is HMAC-SHA256 over ``"{id}.{timestamp}.{raw_body}"`` using the
base64-decoded part of the signing secret that follows the ``whsec_`` prefix.

The ``webhook-*`` header names from the Standard Webhooks spec use the same
algorithm; they are accepted too so a future header rename cannot break us.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import time
from collections.abc import Mapping

_ID_HEADERS = ("svix-id", "webhook-id")
_TIMESTAMP_HEADERS = ("svix-timestamp", "webhook-timestamp")
_SIGNATURE_HEADERS = ("svix-signature", "webhook-signature")
_SECRET_PREFIX = "whsec_"


class WebhookVerificationError(Exception):
    """The request is not an authentic, fresh Resend webhook (-> HTTP 400)."""


class WebhookSecretError(Exception):
    """The server-side signing secret is unusable (-> HTTP 500, our bug)."""


def _header(headers: Mapping[str, str], names: tuple[str, ...]) -> str | None:
    for name in names:
        value = headers.get(name)
        if value:
            return value
    return None


def _decode_secret(secret: str) -> bytes:
    material = secret.strip()
    if material.startswith(_SECRET_PREFIX):
        material = material[len(_SECRET_PREFIX):]
    material += "=" * (-len(material) % 4)  # tolerate stripped padding
    try:
        key = base64.b64decode(material, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise WebhookSecretError("RESEND_WEBHOOK_SECRET is not valid base64") from exc
    if not key:
        raise WebhookSecretError("RESEND_WEBHOOK_SECRET is empty")
    return key


def get_message_id(headers: Mapping[str, str]) -> str | None:
    """Delivery id for log correlation (safe to log)."""
    return _header(headers, _ID_HEADERS)


def verify_webhook(
    payload: bytes,
    headers: Mapping[str, str],
    secret: str,
    *,
    tolerance_seconds: int = 300,
    now: float | None = None,
) -> None:
    """Raise unless ``payload`` is a correctly signed, recent Resend webhook.

    ``payload`` MUST be the exact raw request body bytes. Re-serialising parsed
    JSON changes whitespace/ordering and breaks the signature.
    """
    msg_id = _header(headers, _ID_HEADERS)
    timestamp = _header(headers, _TIMESTAMP_HEADERS)
    signature_header = _header(headers, _SIGNATURE_HEADERS)
    if not (msg_id and timestamp and signature_header):
        raise WebhookVerificationError("Missing webhook signature headers")

    try:
        sent_at = int(timestamp)
    except ValueError as exc:
        raise WebhookVerificationError("Malformed webhook timestamp") from exc

    current = time.time() if now is None else now
    if abs(current - sent_at) > tolerance_seconds:
        raise WebhookVerificationError("Webhook timestamp outside allowed tolerance")

    key = _decode_secret(secret)
    signed_content = f"{msg_id}.{timestamp}.".encode() + payload
    expected = base64.b64encode(hmac.new(key, signed_content, hashlib.sha256).digest())

    # The header may carry several signatures (secret rotation). Accept any v1 match.
    for candidate in signature_header.split():
        version, _, signature = candidate.partition(",")
        if version == "v1" and hmac.compare_digest(signature.encode(), expected):
            return

    raise WebhookVerificationError("No matching webhook signature")
