"""Signature verification tests, including Svix's published test vectors."""

import pytest

from inbound.security import WebhookSecretError, WebhookVerificationError, verify_webhook

# Test vectors from https://docs.svix.com/receiving/verifying-payloads/
SECRET = "whsec_plJ3nmyCDGBKInavdOK15jsl"
PAYLOAD = b'{"event_type":"ping","data":{"success":true}}'
HEADERS = {
    "svix-id": "msg_loFOjxBNrRLzqYUf",
    "svix-timestamp": "1731705121",
    "svix-signature": "v1,rAvfW3dJ/X/qxhsaXPOyyCGmRKsaKWcsNccKXlIktD0=",
}
NOW = 1731705121


def test_valid_signature_passes():
    verify_webhook(PAYLOAD, HEADERS, SECRET, now=NOW)


def test_second_official_vector():
    verify_webhook(
        b'{"test": 2432232314}',
        {
            "svix-id": "msg_p5jXN8AQM9LWM0D4loKWxJek",
            "svix-timestamp": "1614265330",
            "svix-signature": "v1,g0hM9SsE+OTPJTGt/tmIKtSyZlE3uFJELVlNIOLJ1OE=",
        },
        "whsec_MfKQ9r8GKYqrTwjUPD8ILPZIo2LaLaSw",
        now=1614265330,
    )


def test_standard_webhooks_header_names_are_accepted():
    headers = {
        "webhook-id": HEADERS["svix-id"],
        "webhook-timestamp": HEADERS["svix-timestamp"],
        "webhook-signature": HEADERS["svix-signature"],
    }
    verify_webhook(PAYLOAD, headers, SECRET, now=NOW)


def test_any_of_multiple_signatures_may_match():
    headers = {**HEADERS, "svix-signature": "v1,AAAA " + HEADERS["svix-signature"]}
    verify_webhook(PAYLOAD, headers, SECRET, now=NOW)


@pytest.mark.parametrize(
    "payload, headers, secret, now",
    [
        (PAYLOAD + b" ", HEADERS, SECRET, NOW),                              # body changed
        (PAYLOAD, HEADERS, "whsec_MfKQ9r8GKYqrTwjUPD8ILPZIo2LaLaSw", NOW),   # wrong secret
        (PAYLOAD, HEADERS, SECRET, NOW + 301),                               # too old
        (PAYLOAD, HEADERS, SECRET, NOW - 301),                               # too far in future
        (PAYLOAD, {}, SECRET, NOW),                                          # no headers
        (PAYLOAD, {**HEADERS, "svix-timestamp": "abc"}, SECRET, NOW),        # bad timestamp
        (PAYLOAD, {**HEADERS, "svix-signature": "v2,xxxx"}, SECRET, NOW),    # unknown version
    ],
)
def test_bad_requests_are_rejected(payload, headers, secret, now):
    with pytest.raises(WebhookVerificationError):
        verify_webhook(payload, headers, secret, now=now)


def test_unusable_server_secret_is_a_config_error_not_a_client_error():
    with pytest.raises(WebhookSecretError):
        verify_webhook(PAYLOAD, HEADERS, "whsec_!!!not-base64", now=NOW)
