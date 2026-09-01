"""Direct tests for api/app.py's own assembly logic not already covered
by the end-to-end router tests: the model-gateway factory's two branches,
and the /healthz endpoint."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from config.settings import load_settings

from api.app import _model_gateway_factory, create_app

pytestmark = pytest.mark.unit


def test_factory_returns_none_without_an_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    factory = _model_gateway_factory(load_settings())
    assert factory() is None


def test_factory_returns_a_real_gateway_with_an_api_key_present(monkeypatch: pytest.MonkeyPatch) -> None:
    # Constructing a ModelGateway never makes a network call - only a
    # real .call() would, which this test never triggers.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-fake-for-this-test-only")
    factory = _model_gateway_factory(load_settings())
    gateway = factory()
    assert gateway is not None


def test_healthz(tmp_path: Path) -> None:
    app = create_app(settings=load_settings(), base_path=tmp_path, require_auth=False)
    client = TestClient(app)
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
