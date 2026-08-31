from __future__ import annotations

import pytest
from pydantic import ValidationError

from config.settings import Environment, FeatureFlags, PlatformSettings, load_settings


def test_default_platform_yaml_loads() -> None:
    settings = load_settings()
    assert settings.environment == Environment.DEV
    assert settings.models.tiers["fast"].tier_id == "fast-v1"
    assert settings.storage.pgvector_enabled is True
    assert settings.egress.fail_mode == "closed"
    assert settings.egress.policy_version == 1


def test_feature_flags_dotted_translation() -> None:
    settings = load_settings()
    assert settings.feature_flags.acord_ingestion_enabled is False
    assert settings.feature_flags.inference_enabled is True
    assert settings.feature_flags.critic_secondary_provider is True
    assert settings.feature_flags.gate_dpo_override_enabled is False
    assert settings.feature_flags.emission_strict_determinism is True


def test_feature_flags_from_dotted_defaults_when_key_absent() -> None:
    flags = FeatureFlags.from_dotted({})
    assert flags == FeatureFlags()


def test_egress_fail_mode_rejects_anything_but_closed() -> None:
    with pytest.raises(ValidationError):
        PlatformSettings.model_validate({
            "environment": Environment.DEV,
            "models": {
                "tiers": {"fast": {"provider": "primary", "tier_id": "fast-v1", "max_tokens": 100}},
                "embedding_tier_id": "embed-v1",
                "embedding_dimensions": 8,
            },
            "storage": {"postgres_dsn": "postgresql://x/y"},
            "egress": {"policy_version": 1, "fail_mode": "open"},
            "feature_flags": {},
        })
