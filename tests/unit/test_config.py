from __future__ import annotations

import pytest
from pydantic import ValidationError

from config.settings import (
    Environment,
    FeatureFlags,
    PlatformSettings,
    RelevanceConfig,
    load_settings,
)


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


def test_storage_run_store_path_default() -> None:
    settings = load_settings()
    assert settings.storage.run_store_path == "run-store"


def test_relevance_config_loads_spec_verbatim_values() -> None:
    settings = load_settings()
    assert settings.relevance.pass1_keep == 0.65
    assert settings.relevance.pass1_drop == 0.20
    assert settings.relevance.domain_tokens["claims"] == [
        "claim", "fnol", "loss", "incident", "claimant", "settlement", "reserve", "sinistre",
    ]
    assert settings.relevance.pass1_weights == {
        "path": 0.60, "catalogue": 0.20, "gateway": 0.10, "kind": 0.10,
    }
    assert "application/yaml" in settings.relevance.contract_media_types


def test_relevance_config_rejects_drop_above_keep() -> None:
    with pytest.raises(ValidationError):
        RelevanceConfig(pass1_keep=0.5, pass1_drop=0.6, domain_tokens={})


def test_relevance_config_allows_drop_equal_to_keep() -> None:
    cfg = RelevanceConfig(pass1_keep=0.5, pass1_drop=0.5, domain_tokens={})
    assert cfg.pass1_drop == cfg.pass1_keep


def _valid_settings_payload() -> dict[str, object]:
    return {
        "environment": Environment.DEV,
        "models": {
            "tiers": {"fast": {"provider": "primary", "tier_id": "fast-v1", "max_tokens": 100}},
            "embedding_tier_id": "embed-v1",
            "embedding_dimensions": 8,
        },
        "storage": {"postgres_dsn": "postgresql://x/y"},
        "egress": {"policy_version": 1, "fail_mode": "closed"},
        "feature_flags": {},
        "relevance": {"pass1_keep": 0.65, "pass1_drop": 0.20, "domain_tokens": {}},
    }


def test_egress_fail_mode_rejects_anything_but_closed() -> None:
    payload = _valid_settings_payload()
    payload["egress"] = {"policy_version": 1, "fail_mode": "open"}
    with pytest.raises(ValidationError):
        PlatformSettings.model_validate(payload)


def test_platform_settings_accepts_valid_relevance_config() -> None:
    settings = PlatformSettings.model_validate(_valid_settings_payload())
    assert settings.relevance.pass1_keep == 0.65
