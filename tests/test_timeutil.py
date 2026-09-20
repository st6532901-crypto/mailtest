from datetime import datetime, timedelta, timezone

from inbound.timeutil import parse_timestamp


def test_webhook_format():
    assert parse_timestamp("2026-02-22T23:41:11.894Z") == datetime(2026, 2, 22, 23, 41, 11, 894000, tzinfo=timezone.utc)


def test_list_api_format_with_short_utc_offset():
    assert parse_timestamp("2025-10-09 14:37:40.951732+00") == datetime(
        2025, 10, 9, 14, 37, 40, 951732, tzinfo=timezone.utc
    )


def test_explicit_offset_is_preserved():
    assert parse_timestamp("2025-10-09T14:37:40+05:30").utcoffset() == timedelta(hours=5, minutes=30)


def test_unparseable_values_are_returned_unchanged():
    assert parse_timestamp("garbage") == "garbage"
    assert parse_timestamp(None) is None
