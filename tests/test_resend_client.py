import io
import json
import urllib.error

import pytest

from inbound import resend_client
from inbound.resend_client import ResendApiError, list_received_emails

KEY = "re_secret_key_value"


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _install(monkeypatch, payload=None, error=None):
    seen = {}

    def fake_urlopen(request, timeout):
        seen["request"] = request
        seen["timeout"] = timeout
        if error:
            raise error
        return FakeResponse(json.dumps(payload).encode())

    monkeypatch.setattr(resend_client.urllib.request, "urlopen", fake_urlopen)
    return seen


def test_parses_list_response_and_maps_id_to_email_id(monkeypatch):
    seen = _install(monkeypatch, {
        "object": "list", "has_more": False,
        "data": [
            {"id": "a1", "from": "s@gmail.com", "to": ["r@x.resend.app"], "cc": [], "bcc": [],
             "subject": "Hello", "created_at": "2025-10-09 14:37:40.951732+00", "message_id": "<m@x>",
             "attachments": []},
            {"unexpected": "shape"},  # skipped, not fatal
        ],
    })
    emails = list_received_emails(KEY, 20)

    assert [e.email_id for e in emails] == ["a1"]
    assert emails[0].sender == "s@gmail.com"
    assert emails[0].received_at.year == 2025

    req = seen["request"]
    assert req.full_url == "https://api.resend.com/emails/receiving?limit=20"
    assert req.get_header("Authorization") == f"Bearer {KEY}"
    assert req.get_header("User-agent")  # Resend requires a User-Agent
    assert seen["timeout"] > 0


@pytest.mark.parametrize("code", [401, 403, 429, 500])
def test_http_errors_become_safe_messages(monkeypatch, code):
    _install(monkeypatch, error=urllib.error.HTTPError("https://api.resend.com", code, "err", {}, None))
    with pytest.raises(ResendApiError) as exc:
        list_received_emails(KEY, 10)
    assert str(code) in str(exc.value)
    assert KEY not in str(exc.value)


def test_network_failure_is_reported_without_details(monkeypatch):
    _install(monkeypatch, error=urllib.error.URLError("dns failure"))
    with pytest.raises(ResendApiError, match="Could not reach"):
        list_received_emails(KEY, 10)


def test_unexpected_json_is_reported(monkeypatch):
    _install(monkeypatch, {"nope": True})
    with pytest.raises(ResendApiError, match="Unexpected response"):
        list_received_emails(KEY, 10)
