from __future__ import annotations

import pytest
from pydantic import ValidationError

from config.settings import (
    ClusteringConfig,
    CoverageConfig,
    EgressConfig,
    Environment,
    FeatureFlags,
    ModelProvider,
    ModelTierConfig,
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


def test_default_platform_yaml_model_ids_are_set_for_the_two_tiers_agents_use() -> None:
    settings = load_settings()
    assert settings.models.tiers["fast"].model_id == "claude-haiku-4-5-20251001"
    assert settings.models.tiers["high"].model_id == "claude-sonnet-5"


def test_default_platform_yaml_critic_tier_has_no_model_id_yet() -> None:
    # Section 19.2's degraded mode: no secondary provider is configured in
    # this PoC - "critic runs on the primary provider with a distinct
    # prompt lineage" - model_id stays unset until an increment that
    # actually builds the adversarial critic needs it.
    settings = load_settings()
    assert settings.models.tiers["critic"].model_id is None


def test_model_tier_config_model_id_defaults_to_none() -> None:
    tier = ModelTierConfig(provider=ModelProvider.PRIMARY, tier_id="fast-v1", max_tokens=8000)
    assert tier.model_id is None


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


def test_clustering_config_loads_spec_verbatim_values() -> None:
    settings = load_settings()
    # weights is a documented, deliberate departure from the spec's own
    # 0.20/0.30/0.15/0.20/0.15 - see ClusteringConfig.weights' own
    # description. Only sum-to-1.0 and the embedding discount are asserted
    # here; abbreviations/type_compatibility below are spec-verbatim.
    assert abs(sum(settings.clustering.weights.values()) - 1.0) < 1e-9
    assert settings.clustering.weights["embedding"] < 0.15
    assert settings.clustering.abbreviations["dt"] == "date"
    assert settings.clustering.abbreviations["sinistre"] == "claim"
    assert settings.clustering.link_threshold == 0.72
    assert settings.clustering.review_band_low == 0.55
    assert settings.clustering.block_top_k == 25
    assert settings.clustering.block_max_size == 40
    pairs = {(e.a, e.b): e.score for e in settings.clustering.type_compatibility}
    assert pairs[("string", "string")] == 1.0
    assert pairs[("date", "dateTime")] == 0.85


def test_clustering_config_rejects_review_band_above_link_threshold() -> None:
    with pytest.raises(ValidationError):
        ClusteringConfig(link_threshold=0.5, review_band_low=0.6)


def test_clustering_config_allows_review_band_equal_to_link_threshold() -> None:
    cfg = ClusteringConfig(link_threshold=0.5, review_band_low=0.5)
    assert cfg.review_band_low == cfg.link_threshold


def test_clustering_config_defaults_when_omitted() -> None:
    settings = PlatformSettings.model_validate(_valid_settings_payload())
    assert settings.clustering.link_threshold == 0.72


def test_coverage_config_loads_spec_verbatim_values() -> None:
    settings = load_settings()
    assert settings.coverage.region_floor == 0.85
    assert settings.coverage.domain_target == 0.90
    assert settings.coverage.resolution_weights.core == 1.0
    assert settings.coverage.resolution_weights.extension == 0.5
    assert settings.coverage.resolution_weights.gap == 0.0


def test_coverage_config_defaults_when_omitted() -> None:
    cfg = CoverageConfig()
    assert cfg.region_floor == 0.85
    assert cfg.domain_target == 0.90


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
