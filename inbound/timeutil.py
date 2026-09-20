"""Tolerant timestamp parsing (standard library only)."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

# e.g. "2025-10-09 14:37:40.951732+00": ISO-ish, but with a two-digit UTC offset.
_SHORT_OFFSET = re.compile(r"^(?P<head>.+\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?)(?P<off>[+-]\d{2})$")


def parse_timestamp(value: Any) -> Any:
    """Turn the timestamp formats Resend uses into a ``datetime``.

    Resend's webhook uses ``2026-02-22T23:41:11.894Z``; its Receiving API docs
    have shown both that and ``2025-10-09 14:37:40.951732+00``. Anything we
    cannot parse is returned unchanged so pydantic can report a clear error.
    """
    if not isinstance(value, str):
        return value
    text = value.strip()
    if text[-1:] in ("Z", "z"):
        text = text[:-1] + "+00:00"
    else:
        match = _SHORT_OFFSET.match(text)
        if match:
            text = f"{match['head']}{match['off']}:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return value
