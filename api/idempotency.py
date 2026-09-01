"""
In-process idempotency-key store (Section 12.1: "Idempotency keys on
every mutating endpoint. A repeated key returns the original result
rather than acting twice"). A plain dict keyed by (route, key) -> the
first response body returned for that key - non-persistent,
single-process, PoC-scope. A real deployment needs a distributed store
(Redis, a database table) surviving process restarts and multiple
server instances; this module is explicit that it is not that.
"""

from __future__ import annotations

import threading
from typing import Any


class IdempotencyStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._responses: dict[tuple[str, str], Any] = {}

    def get(self, route: str, key: str | None) -> Any | None:
        if key is None:
            return None
        with self._lock:
            return self._responses.get((route, key))

    def put(self, route: str, key: str | None, response: Any) -> None:
        """setdefault, not assignment: under a genuine concurrent replay
        the FIRST recorded response wins - "the original result", per
        Section 12.1's own wording, not whichever request happened to
        finish last."""
        if key is None:
            return
        with self._lock:
            self._responses.setdefault((route, key), response)
