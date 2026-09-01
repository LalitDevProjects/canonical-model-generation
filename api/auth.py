"""
A structural stand-in for Section 12.1's own "REST over HTTPS with mTLS
between components; OAuth 2.0 client credentials for human-facing
clients." Real mTLS/OIDC/workload-identity infrastructure cannot be
stood up as pure application code in this environment - this checks a
single static bearer token (config/settings.py::ApiConfig.bearer_token),
the same PoC-placeholder-credential status EgressConfig.ledger_signing_key
already carries for its own key material. This is explicitly NOT Section
12.1's own real security model.
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import Header, HTTPException

from config.settings import PlatformSettings

BearerTokenDependency = Callable[[str | None], None]


def make_bearer_token_dependency(settings: PlatformSettings) -> BearerTokenDependency:
    expected = f"Bearer {settings.api.bearer_token}"

    def require_bearer_token(authorization: str | None = Header(default=None)) -> None:
        if authorization != expected:
            raise HTTPException(status_code=401, detail="missing or invalid bearer token")

    return require_bearer_token
