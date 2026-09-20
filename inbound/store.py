"""Temporary in-memory storage of the latest received emails.

THIS IS NOT PERSISTENT. It lives in one Python process:

* it is lost whenever the process restarts (every Vercel cold start / deploy);
* on Vercel each request may be served by a different instance, so an email
  received by one instance is not visible to the others.

That is why the dashboard also reads Resend's own Receiving API (see
``inbox.py``): Resend is the durable record, this store is only a fast,
best-effort copy of the webhook events this instance has seen.
"""

from __future__ import annotations

import threading
from collections import OrderedDict

from inbound.schemas import EmailOut

MAX_EMAILS = 50


class InMemoryEmailStore:
    def __init__(self, max_items: int = MAX_EMAILS) -> None:
        self._max_items = max_items
        self._items: OrderedDict[str, EmailOut] = OrderedDict()
        self._lock = threading.Lock()

    def add(self, email: EmailOut) -> bool:
        """Remember ``email``. Returns False if this email_id was already stored."""
        with self._lock:
            if email.email_id in self._items:
                return False
            self._items[email.email_id] = email
            while len(self._items) > self._max_items:
                self._items.popitem(last=False)  # drop the oldest
            return True

    def latest(self, limit: int) -> list[EmailOut]:
        """Newest first."""
        with self._lock:
            items = list(self._items.values())
        items.sort(key=lambda e: (e.received_at, e.email_id), reverse=True)
        return items[:limit]

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()


# One store per running process.
email_store = InMemoryEmailStore()
