"""FastAPI application factory. Imported by api/index.py (Vercel) and uvicorn."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request

from inbound.config import configure_logging
from inbound.routes import dashboard, emails, health, webhook

configure_logging()
logger = logging.getLogger("inbound")

app = FastAPI(
    title="SIH Inbound Mail Receiver",
    description="Receives real inbound email via Resend webhooks and lists it.",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url=None,
    openapi_url="/api/openapi.json",
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    if request.url.path.startswith("/api/"):
        response.headers.setdefault("Cache-Control", "no-store")
    return response


app.include_router(dashboard.router)
app.include_router(emails.router)
app.include_router(webhook.router)
app.include_router(health.router)
