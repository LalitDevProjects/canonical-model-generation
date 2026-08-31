from __future__ import annotations

import pytest
from pydantic import ValidationError

from config.settings import (
    EgressConfig,
    Environment,
    FeatureFlags,
    PlatformSettings,
    RelevanceConfig,
    load_settings,
)

_VALID_HEX64 = "a" * 64


def test_default_platform_yaml_loads() -> None:
    settings = load_settings()
    assert settings.environment == Environment.DEV
    assert settings.models.tiers["fast"].tier_id == "fast-v1"
    assert settings.storage.pgvector_enabled is True
    assert settings.egress.fail_mode == "closed"
    assert settings.egress.policy_version == 3


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


def _valid_egress_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "policy_version": 3,
        "fail_mode": "closed",
        "lawful_basis": "legitimate-interest",
        "ledger_signing_key": _VALID_HEX64,
        "tokenisation_keys": {"us": _VALID_HEX64, "uk": _VALID_HEX64, "eu": _VALID_HEX64},
    }
    payload.update(overrides)
    return payload


def _valid_settings_payload() -> dict[str, object]:
    return {
        "environment": Environment.DEV,
        "models": {
            "tiers": {"fast": {"provider": "primary", "tier_id": "fast-v1", "max_tokens": 100}},
            "embedding_tier_id": "embed-v1",
            "embedding_dimensions": 8,
        },
        "storage": {"postgres_dsn": "postgresql://x/y"},
        "egress": _valid_egress_payload(),
        "feature_flags": {},
        "relevance": {"pass1_keep": 0.65, "pass1_drop": 0.20, "domain_tokens": {}},
    }


def test_egress_fail_mode_rejects_anything_but_closed() -> None:
    with pytest.raises(ValidationError, match="fail_mode"):
        EgressConfig.model_validate(_valid_egress_payload(fail_mode="open"))


def test_egress_lawful_basis_defaults() -> None:
    payload = _valid_egress_payload()
    del payload["lawful_basis"]
    cfg = EgressConfig.model_validate(payload)
    assert cfg.lawful_basis == "legitimate-interest"


def test_egress_rejects_short_ledger_signing_key() -> None:
    with pytest.raises(ValidationError, match="ledger_signing_key"):
        EgressConfig.model_validate(_valid_egress_payload(ledger_signing_key="tooshort"))


def test_egress_rejects_non_hex_ledger_signing_key() -> None:
    with pytest.raises(ValidationError, match="ledger_signing_key"):
        EgressConfig.model_validate(_valid_egress_payload(ledger_signing_key="z" * 64))


def test_egress_rejects_missing_region_tokenisation_key() -> None:
    payload = _valid_egress_payload()
    payload["tokenisation_keys"] = {"us": _VALID_HEX64, "uk": _VALID_HEX64}  # eu missing
    with pytest.raises(ValidationError, match="eu"):
        EgressConfig.model_validate(payload)


def test_egress_rejects_malformed_region_tokenisation_key() -> None:
    payload = _valid_egress_payload()
    payload["tokenisation_keys"] = {"us": "short", "uk": _VALID_HEX64, "eu": _VALID_HEX64}
    with pytest.raises(ValidationError, match="tokenisation_keys"):
        EgressConfig.model_validate(payload)


def test_default_platform_yaml_egress_keys_are_well_formed() -> None:
    settings = load_settings()
    assert len(settings.egress.ledger_signing_key) == 64
    assert set(settings.egress.tokenisation_keys) == {"us", "uk", "eu"}


def test_platform_settings_accepts_valid_relevance_config() -> None:
    settings = PlatformSettings.model_validate(_valid_settings_payload())
    assert settings.relevance.pass1_keep == 0.65
