"""Minimal read-only client for Resend's "List Received Emails" API.

    GET https://api.resend.com/emails/receiving

Standard library only (no extra dependency). The API key is used server-side
and is never sent to the browser, logged, or included in error messages.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request

from pydantic import ValidationError

from inbound.schemas import ReceivedEmailData

logger = logging.getLogger("inbound.resend")

RECEIVING_URL = "https://api.resend.com/emails/receiving"
USER_AGENT = "sih-inbound-mail/1.0"  # Resend's API rejects requests without a User-Agent
TIMEOUT_SECONDS = 8.0


class ResendApiError(Exception):
    """The Resend API could not be read. The message is safe to show to users."""


def list_received_emails(api_key: str, limit: int) -> list[ReceivedEmailData]:
    request = urllib.request.Request(
        f"{RECEIVING_URL}?limit={int(limit)}",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310 - fixed https URL
            body = response.read()
    except urllib.error.HTTPError as exc:
        hint = {
            401: "API key rejected",
            403: "API key not allowed to read received emails",
            429: "rate limited",
        }.get(exc.code, "request failed")
        raise ResendApiError(f"Resend API returned HTTP {exc.code} ({hint})") from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise ResendApiError("Could not reach the Resend API") from None

    try:
        payload = json.loads(body)
        items = payload["data"]
        if not isinstance(items, list):
            raise TypeError("data is not a list")
    except (ValueError, KeyError, TypeError):
        raise ResendApiError("Unexpected response from the Resend API") from None

    emails: list[ReceivedEmailData] = []
    for item in items:
        try:
            # The list API calls the email id "id"; the webhook calls it "email_id".
            emails.append(ReceivedEmailData.model_validate({**item, "email_id": item.get("id")}))
        except (ValidationError, AttributeError, TypeError):
            logger.warning("Skipping a received email with an unexpected shape")
    return emails
