"""GET /api/emails - latest received emails as JSON (newest first)."""

from __future__ import annotations

from fastapi import APIRouter, Query
from fastapi.concurrency import run_in_threadpool

from inbound.inbox import collect_emails
from inbound.schemas import EmailListOut
from inbound.store import MAX_EMAILS

router = APIRouter()


@router.get("/api/emails", response_model=EmailListOut, tags=["emails"])
async def get_emails(
    limit: int = Query(MAX_EMAILS, ge=1, le=MAX_EMAILS, description="Maximum number of emails to return"),
) -> EmailListOut:
    # collect_emails does blocking network I/O (Resend API), so keep it off the event loop.
    emails, sources = await run_in_threadpool(collect_emails, limit)
    return EmailListOut(count=len(emails), emails=emails, sources=sources)
