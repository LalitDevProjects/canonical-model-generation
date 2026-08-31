"""
Platform configuration (Section 15). Hand-written pydantic-settings module,
not a 12th schema-generated contract: config isn't one of the C1-C11
contracts, and nothing generates *from* it the way generated/ is produced
from contracts/ - a deliberate Increment 1 scope call, distinct from the
"contracts get JSON Schema then codegen" rule that governs contracts/.

Layering (lowest to highest precedence, pydantic-settings default order):
platform defaults (this module) -> config/platform.yaml -> environment
variables (CMGP_ prefix, "__" as the nested delimiter, e.g.
CMGP_EGRESS__FAIL_MODE=closed).
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_PLATFORM_YAML = Path(__file__).resolve().parent / "platform.yaml"


class Environment(str, Enum):
    DEV = "dev"
    STAGING = "staging"
    PROD = "prod"


class ModelProvider(str, Enum):
    PRIMARY = "primary"
    SECONDARY = "secondary"


class ModelTierConfig(BaseModel):
    provider: ModelProvider
    tier_id: str = Field(
        description="Opaque tier identifier, e.g. 'fast-v1'. NOT a concrete "
        "model name: the spec treats the model provider agreement as a "
        "contractual precondition (Section 13, D3), not a configuration "
        "value, so no concrete provider/model is named here at Increment 1. "
        "A model gateway resolves tier_id to an actual provider call once "
        "Increment 6 wires one in."
    )
    max_tokens: int = Field(gt=0)


class ModelsConfig(BaseModel):
    tiers: dict[str, ModelTierConfig]
    embedding_tier_id: str
    embedding_dimensions: int = Field(gt=0)


class StorageConfig(BaseModel):
    postgres_dsn: str = Field(
        description="Placeholder at Increment 1: local Postgres + pgvector "
        "is the intended target (infra/docker-compose.yml) but no runtime "
        "code in this increment connects to it."
    )
    pgvector_enabled: bool = True
    run_store_path: str = Field(
        default="run-store",
        description="Base directory for run-store/{runId}/... (Section 3.7). "
        "A relative path resolves against the repository root "
        "(pipeline.run_store.RunStore), not the process's working directory.",
    )


class RelevanceConfig(BaseModel):
    """Pass-1 deterministic relevance filtering (Section 4.2). pass1_keep/
    pass1_drop/domain_tokens values are transcribed verbatim from the
    spec's own config/platform.yaml example (Section 15.1); pass1_weights
    and contract_media_types have no spec-given example and are Increment
    2 builder defaults."""

    pass1_keep: float = Field(ge=0.0, le=1.0)
    pass1_drop: float = Field(ge=0.0, le=1.0)
    domain_tokens: dict[str, list[str]]
    pass1_weights: dict[str, float] = Field(
        default_factory=lambda: {"path": 0.60, "catalogue": 0.20, "gateway": 0.10, "kind": 0.10}
    )
    contract_media_types: list[str] = Field(
        default_factory=lambda: [
            "application/json",
            "application/yaml",
            "application/x-yaml",
            "application/vnd.oai.openapi",
            "application/schema+json",
            "application/xml",
            "application/vnd.apache.avro+json",
        ]
    )

    @model_validator(mode="after")
    def _drop_not_above_keep(self) -> "RelevanceConfig":
        if self.pass1_drop > self.pass1_keep:
            raise ValueError("relevance.pass1_drop must not exceed relevance.pass1_keep")
        return self


class EgressConfig(BaseModel):
    policy_version: int
    fail_mode: str = Field(
        default="closed",
        pattern="^closed$",
        description="Hard-locked: the spec states the code MUST reject any "
        "value other than 'closed'. Modelled as a pattern constraint, not "
        "just a default, so any other value is a load-time validation "
        "error rather than a silently-accepted misconfiguration.",
    )


class FeatureFlags(BaseModel):
    """The five feature flags named in Section 15.3, mapped to snake_case
    Python attributes (dots aren't valid identifiers); config/platform.yaml
    keeps the spec's own dotted on-disk spelling."""

    acord_ingestion_enabled: bool = False
    inference_enabled: bool = True
    critic_secondary_provider: bool = True
    gate_dpo_override_enabled: bool = False
    emission_strict_determinism: bool = True

    @classmethod
    def from_dotted(cls, raw: dict[str, Any]) -> "FeatureFlags":
        return cls(
            acord_ingestion_enabled=raw.get("acord.ingestion.enabled", False),
            inference_enabled=raw.get("inference.enabled", True),
            critic_secondary_provider=raw.get("critic.secondary_provider", True),
            gate_dpo_override_enabled=raw.get("gate.dpo_override.enabled", False),
            emission_strict_determinism=raw.get("emission.strict_determinism", True),
        )


class PlatformSettings(BaseSettings):
    """Environment variables (CMGP_ prefix, '__' nested delimiter, e.g.
    CMGP_EGRESS__FAIL_MODE=closed) can supply or override any field not
    otherwise provided. load_settings() below is the normal entrypoint: it
    reads config/platform.yaml and passes every field as an explicit
    constructor kwarg, which pydantic-settings treats as its
    highest-precedence source - so env vars only fill in what the loaded
    YAML doesn't set. Automatic YAML-file loading via pydantic-settings'
    own YamlConfigSettingsSource is deliberately not used here: it maps
    YAML keys to field names directly, which doesn't compose with
    FeatureFlags' dotted-vs-snake_case translation (see
    FeatureFlags.from_dotted) - that translation has to happen before
    construction regardless, so load_settings() does the whole read+
    translate+construct sequence itself.
    """

    model_config = SettingsConfigDict(env_prefix="CMGP_", env_nested_delimiter="__")

    environment: Environment
    models: ModelsConfig
    storage: StorageConfig
    egress: EgressConfig
    feature_flags: FeatureFlags
    relevance: RelevanceConfig


def load_settings(yaml_path: Path | None = None) -> PlatformSettings:
    """Load settings from config/platform.yaml (or yaml_path). The
    feature_flags section uses the spec's dotted key spelling
    (acord.ingestion.enabled, etc.) and is translated to the snake_case
    attribute names PlatformSettings expects via FeatureFlags.from_dotted
    before construction."""
    import yaml as _yaml

    path = yaml_path or DEFAULT_PLATFORM_YAML
    raw: dict[str, Any] = _yaml.safe_load(path.read_text())

    feature_flags_raw = raw.pop("feature_flags", {})
    raw["feature_flags"] = FeatureFlags.from_dotted(feature_flags_raw).model_dump()

    return PlatformSettings(**raw)
