"""Direct unit tests for api/pagination.py - the PoC-scope cursor
encoding (a plain base64 integer, not a cryptographically opaque token,
per that module's own docstring)."""

from __future__ import annotations

import pytest

from api.pagination import InvalidCursorError, decode_cursor, encode_cursor


def test_round_trip() -> None:
    assert decode_cursor(encode_cursor(42)) == 42


def test_zero_round_trips() -> None:
    assert decode_cursor(encode_cursor(0)) == 0


def test_malformed_cursor_raises() -> None:
    with pytest.raises(InvalidCursorError):
        decode_cursor("not-a-real-cursor!!")
