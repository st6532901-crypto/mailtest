"""Pydantic models: inbound webhook validation and API responses."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from inbound.timeutil import parse_timestamp

# Defensive limits: the sender controls these strings, so bound them.
MAX_ID_LEN = 500
MAX_ADDRESS_LEN = 1000
MAX_SUBJECT_LEN = 2000
MAX_RECIPIENTS = 200


def _clean(value: str, limit: int) -> str:
    # NUL bytes are never legitimate in display text and break many consumers.
    return value.replace("\x00", "").strip()[:limit]


# --------------------------------------------------------------------------- #
# Inbound (Resend -> us)
# --------------------------------------------------------------------------- #
class ResendEvent(BaseModel):
    """Envelope common to every Resend webhook."""

    model_config = ConfigDict(extra="ignore")

    type: str
    data: dict[str, Any] = Field(default_factory=dict)


class ReceivedEmailData(BaseModel):
    """``data`` object of an ``email.received`` event (metadata only)."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    email_id: str
    created_at: datetime
    sender: str = Field(alias="from")
    to: list[str] = Field(default_factory=list)
    cc: list[str] = Field(default_factory=list)
    bcc: list[str] = Field(default_factory=list)
    message_id: str | None = None
    subject: str | None = None

    @field_validator("to", "cc", "bcc", mode="before")
    @classmethod
    def _listify(cls, value: Any) -> Any:
        if value is None:
            return []
        if isinstance(value, str):
            return [value]
        return value

    @field_validator("to", "cc", "bcc", mode="after")
    @classmethod
    def _clean_addresses(cls, value: list[str]) -> list[str]:
        cleaned = (_clean(item, MAX_ADDRESS_LEN) for item in value[:MAX_RECIPIENTS])
        return [item for item in cleaned if item]

    @field_validator("email_id", mode="after")
    @classmethod
    def _clean_email_id(cls, value: str) -> str:
        value = _clean(value, MAX_ID_LEN)
        if not value:
            raise ValueError("email_id must not be empty")
        return value

    @field_validator("sender", mode="after")
    @classmethod
    def _clean_sender(cls, value: str) -> str:
        value = _clean(value, MAX_ADDRESS_LEN)
        if not value:
            raise ValueError("from must not be empty")
        return value

    @field_validator("message_id", mode="after")
    @classmethod
    def _clean_message_id(cls, value: str | None) -> str | None:
        return (_clean(value, MAX_ID_LEN) or None) if value is not None else None

    @field_validator("subject", mode="after")
    @classmethod
    def _clean_subject(cls, value: str | None) -> str | None:
        return _clean(value, MAX_SUBJECT_LEN) if value is not None else None

    @field_validator("created_at", mode="before")
    @classmethod
    def _parse_created_at(cls, value: Any) -> Any:
        return parse_timestamp(value)

    @field_validator("created_at", mode="after")
    @classmethod
    def _to_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @property
    def recipients(self) -> list[str]:
        """to + cc + bcc, de-duplicated, order preserved."""
        return list(dict.fromkeys([*self.to, *self.cc, *self.bcc]))

    @property
    def received_at(self) -> datetime:
        return self.created_at


# --------------------------------------------------------------------------- #
# Outbound (us -> dashboard)
# --------------------------------------------------------------------------- #
class EmailOut(BaseModel):
    """What the dashboard shows for one received email (metadata only)."""

    email_id: str
    message_id: str | None = None
    sender: str
    recipients: list[str]
    subject: str | None = None
    received_at: datetime
    status: Literal["received"] = "received"

    @classmethod
    def from_data(cls, data: ReceivedEmailData) -> "EmailOut":
        return cls(
            email_id=data.email_id,
            message_id=data.message_id,
            sender=data.sender,
            recipients=data.recipients,
            subject=data.subject,
            received_at=data.received_at,
        )


class SourceStatus(BaseModel):
    """Where the list came from, so the dashboard can be honest about it."""

    resend_api: Literal["ok", "not_configured", "error"]
    resend_api_detail: str | None = None
    memory_count: int


class EmailListOut(BaseModel):
    count: int
    emails: list[EmailOut]
    sources: SourceStatus


class WebhookAck(BaseModel):
    status: Literal["accepted", "duplicate", "ignored"]
    email_id: str | None = None
    event_type: str | None = None
