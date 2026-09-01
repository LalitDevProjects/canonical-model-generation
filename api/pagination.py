"""
Cursor pagination (Section 12.1: "Cursor pagination on all collections.
Offset pagination is prohibited - run artefact sets are large and mutate
during a run"). The cursor here is a plain base64 encoding of an integer
position (a journal seq, or a list index into an already-ordered
collection) - a PoC placeholder, not a cryptographically opaque or
tamper-resistant token a real deployment would want. Documented as such,
not left as a silent gap.
"""

from __future__ import annotations

import base64


class InvalidCursorError(ValueError):
    pass


def encode_cursor(position: int) -> str:
    return base64.urlsafe_b64encode(str(position).encode("ascii")).decode("ascii")


def decode_cursor(cursor: str) -> int:
    try:
        return int(base64.urlsafe_b64decode(cursor.encode("ascii")).decode("ascii"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise InvalidCursorError(f"malformed cursor: {cursor!r}") from exc
