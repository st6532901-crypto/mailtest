"""GET / - the dashboard page (static HTML + a small polling script)."""

from __future__ import annotations

import secrets
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()

_TEMPLATE = Path(__file__).resolve().parent.parent / "templates" / "dashboard.html"


@lru_cache(maxsize=1)
def _load_template() -> str:
    return _TEMPLATE.read_text(encoding="utf-8")


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
async def dashboard() -> HTMLResponse:
    # A per-response nonce lets us ship a strict CSP with inline <script>/<style>.
    nonce = secrets.token_urlsafe(16)
    html = _load_template().replace("{{NONCE}}", nonce)
    csp = (
        "default-src 'none'; "
        f"script-src 'nonce-{nonce}'; "
        f"style-src 'nonce-{nonce}'; "
        "connect-src 'self'; "
        "img-src data:; "
        "base-uri 'none'; "
        "form-action 'none'; "
        "frame-ancestors 'none'"
    )
    return HTMLResponse(html, headers={"Content-Security-Policy": csp, "Cache-Control": "no-store"})
