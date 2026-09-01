"""Hermetic tests for api/auth.py's bearer-token dependency - the
structural stand-in for Section 12.1's own real mTLS/OAuth2 model."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from config.settings import load_settings

from api.app import create_app

pytestmark = pytest.mark.e2e


def _client(tmp_path: Path) -> TestClient:
    app = create_app(settings=load_settings(), base_path=tmp_path, require_auth=True)
    return TestClient(app)


def test_missing_authorization_header_is_401(tmp_path: Path) -> None:
    client = _client(tmp_path)
    response = client.get("/v1/registry/claims/releases")
    assert response.status_code == 401


def test_wrong_bearer_token_is_401(tmp_path: Path) -> None:
    client = _client(tmp_path)
    response = client.get("/v1/registry/claims/releases", headers={"Authorization": "Bearer wrong-token"})
    assert response.status_code == 401


def test_correct_bearer_token_is_accepted(tmp_path: Path) -> None:
    client = _client(tmp_path)
    token = load_settings().api.bearer_token
    response = client.get("/v1/registry/claims/releases", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200


def test_healthz_is_never_gated_by_auth(tmp_path: Path) -> None:
    client = _client(tmp_path)
    response = client.get("/healthz")
    assert response.status_code == 200
