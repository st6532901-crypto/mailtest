"""HTTP-level tests of the real code paths. There is no database anywhere.

The signed requests below are built by the tests themselves; the application
contains no simulation endpoint, so nothing here can create mail at runtime.
"""

import base64
import hashlib
import hmac
import json
import time

import pytest
from fastapi.testclient import TestClient

SECRET_BYTES = b"unit-test-signing-key-0123456789"
SECRET = "whsec_" + base64.b64encode(SECRET_BYTES).decode()
API_KEY = "re_test_key_should_never_leak_123"

EVENT = {
    "type": "email.received",
    "created_at": "2026-09-20T10:00:01.000Z",
    "data": {
        "email_id": "56761188-7520-42d8-8898-ff6fc54ce618",
        "created_at": "2026-09-20T10:00:00.000Z",
        "from": "sender@gmail.com",
        "to": ["inbox@abc123.resend.app"],
        "cc": [],
        "bcc": [],
        "message_id": "<CAF=abc@mail.gmail.com>",
        "subject": "Test Email",
        "attachments": [],
    },
}


def signed_headers(body: bytes, msg_id: str = "msg_test_1", timestamp: int | None = None) -> dict:
    ts = str(int(time.time()) if timestamp is None else timestamp)
    mac = hmac.new(SECRET_BYTES, f"{msg_id}.{ts}.".encode() + body, hashlib.sha256).digest()
    return {
        "content-type": "application/json",
        "svix-id": msg_id,
        "svix-timestamp": ts,
        "svix-signature": "v1," + base64.b64encode(mac).decode(),
    }


@pytest.fixture(autouse=True)
def clean_state():
    from inbound.inbox import reset_cache
    from inbound.store import email_store

    email_store.clear()
    reset_cache()
    yield
    email_store.clear()
    reset_cache()


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("RESEND_WEBHOOK_SECRET", SECRET)
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)  # proves no DB is needed
    from inbound.config import get_settings

    get_settings.cache_clear()
    from inbound.main import app

    with TestClient(app) as test_client:
        yield test_client
    get_settings.cache_clear()


@pytest.fixture
def client_with_api_key(monkeypatch, client):
    from inbound.config import get_settings

    monkeypatch.setenv("RESEND_API_KEY", API_KEY)
    get_settings.cache_clear()
    return client


def post(client, payload, headers=None):
    body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    return client.post("/api/webhook/resend", content=body, headers=headers or signed_headers(body))


# --------------------------------------------------------------------------- webhook
def test_real_signed_event_is_accepted_and_shown_on_the_dashboard_api(client):
    res = post(client, EVENT)
    assert res.status_code == 200
    assert res.json()["status"] == "accepted"

    listing = client.get("/api/emails").json()
    assert listing["count"] == 1
    email = listing["emails"][0]
    assert email["sender"] == "sender@gmail.com"
    assert email["recipients"] == ["inbox@abc123.resend.app"]
    assert email["subject"] == "Test Email"
    assert email["received_at"].startswith("2026-09-20T10:00:00")
    assert email["status"] == "received"
    assert listing["sources"] == {"resend_api": "not_configured", "resend_api_detail": None, "memory_count": 1}


def test_duplicate_delivery_is_acknowledged_and_not_duplicated(client):
    assert post(client, EVENT).json()["status"] == "accepted"
    assert post(client, EVENT).json()["status"] == "duplicate"
    assert client.get("/api/emails").json()["count"] == 1


def test_invalid_signature_is_400_and_nothing_is_kept(client):
    body = json.dumps(EVENT).encode()
    headers = signed_headers(body)
    headers["svix-signature"] = "v1," + base64.b64encode(b"x" * 32).decode()
    assert client.post("/api/webhook/resend", content=body, headers=headers).status_code == 400
    assert client.get("/api/emails").json()["count"] == 0


def test_missing_signature_headers_is_400(client):
    assert client.post("/api/webhook/resend", content=json.dumps(EVENT).encode()).status_code == 400


def test_tampered_body_is_400(client):
    body = json.dumps(EVENT).encode()
    res = client.post("/api/webhook/resend", content=body + b" ", headers=signed_headers(body))
    assert res.status_code == 400


def test_other_event_types_are_acknowledged_and_ignored(client):
    res = post(client, {"type": "email.delivered", "data": {"email_id": "x"}})
    assert res.status_code == 200 and res.json()["status"] == "ignored"
    assert client.get("/api/emails").json()["count"] == 0


def test_signed_but_invalid_email_payload_is_400(client):
    bad = {**EVENT, "data": {"subject": "no email id or sender"}}
    assert post(client, bad).status_code == 400


def test_signed_non_json_body_is_400(client):
    assert post(client, b"not json").status_code == 400


def test_nul_bytes_are_stripped(client):
    evil = {**EVENT, "data": {**EVENT["data"], "subject": "hi\x00there"}}
    assert post(client, evil).status_code == 200
    assert client.get("/api/emails").json()["emails"][0]["subject"] == "hithere"


def test_missing_webhook_secret_is_a_server_error_not_a_pass(client, monkeypatch):
    from inbound.config import get_settings

    monkeypatch.delenv("RESEND_WEBHOOK_SECRET", raising=False)
    get_settings.cache_clear()
    assert post(client, EVENT).status_code == 500


# --------------------------------------------------------------------------- health / dashboard
def test_health_needs_no_database(client):
    res = client.get("/api/health")
    assert res.status_code == 200
    body = res.json()
    assert body["app"] == "running"
    assert body["resend"] == {"webhook_secret_configured": True, "api_key_configured": False}
    assert "database" not in json.dumps(body).lower()


def test_dashboard_is_served_with_strict_csp_and_waiting_message(client):
    res = client.get("/")
    assert res.status_code == 200
    assert "Mail Received" in res.text and "Waiting for incoming email" in res.text
    assert "{{NONCE}}" not in res.text
    csp = res.headers["content-security-policy"]
    assert "default-src 'none'" in csp and "nonce-" in csp


# --------------------------------------------------------------------------- Resend API path
def _api_item(email_id="api-1", subject="From the API", created="2026-09-20T11:00:00.000Z"):
    from inbound.schemas import ReceivedEmailData

    return ReceivedEmailData.model_validate(
        {"email_id": email_id, "created_at": created, "from": "api-sender@outlook.com",
         "to": ["inbox@abc123.resend.app"], "subject": subject}
    )


def test_dashboard_reads_resend_api_and_merges_with_webhook_memory(client_with_api_key, monkeypatch):
    client = client_with_api_key
    monkeypatch.setattr(
        "inbound.inbox.list_received_emails",
        lambda key, limit: [_api_item("api-1"), _api_item(EVENT["data"]["email_id"], "Test Email", "2026-09-20T10:00:00.000Z")],
    )
    post(client, EVENT)  # same email is in both sources -> must appear once

    listing = client.get("/api/emails").json()
    assert listing["sources"]["resend_api"] == "ok"
    assert [e["email_id"] for e in listing["emails"]] == ["api-1", EVENT["data"]["email_id"]]  # newest first


def test_resend_api_failure_falls_back_to_memory_without_leaking_the_key(client_with_api_key, monkeypatch):
    from inbound.resend_client import ResendApiError

    def boom(key, limit):
        raise ResendApiError("Resend API returned HTTP 401 (API key rejected)")

    monkeypatch.setattr("inbound.inbox.list_received_emails", boom)
    post(client_with_api_key, EVENT)

    res = client_with_api_key.get("/api/emails")
    body = res.json()
    assert res.status_code == 200
    assert body["count"] == 1
    assert body["sources"]["resend_api"] == "error"
    assert "401" in body["sources"]["resend_api_detail"]
    assert API_KEY not in res.text


def test_secrets_never_reach_the_browser(client_with_api_key):
    for path in ("/", "/api/emails", "/api/health"):
        text = client_with_api_key.get(path).text
        assert API_KEY not in text and SECRET not in text
