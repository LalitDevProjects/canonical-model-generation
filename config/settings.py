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

import re
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
    model_id: str | None = Field(
        default=None,
        description="Increment 6: the real provider model identifier this "
        "tier_id resolves to (e.g. 'claude-haiku-4-5'), read by "
        "agents/model_gateway.py's Anthropic-backed provider. Kept separate "
        "from tier_id itself - tier_id stays the opaque, model-agnostic "
        "identifier config/platform.yaml and RunManifest.pins.models pin "
        "against; model_id is the concrete resolution, which can change "
        "(a model deprecation, a provider swap) without touching tier_id.",
    )


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


class TypeCompatibilityEntry(BaseModel):
    """One TYPE_COMPATIBILITY table row (Section 9.3). A list of {a, b,
    score} objects, not a dict keyed by a composite type pair - YAML/JSON
    keys must be strings, and a synthesised composite key (e.g.
    "string,date") would be a less legible on-disk format than the spec's
    own tabular presentation."""

    a: str
    b: str
    score: float = Field(ge=0.0, le=1.0)


class ClusteringConfig(BaseModel):
    """Blocking and similarity scoring (Section 9.2-9.3). type_compatibility
    and the ABBREVIATIONS dictionary are transcribed verbatim from the
    spec's own pseudocode; block_top_k/block_max_size match Section 9.2's
    build_blocks(top_k=25) default and Section 8.6's prompt-size ceiling
    (dedupe_blocks(max_size=40)).

    weights is NOT the spec's literal 0.20/0.30/0.15/0.20/0.15 - see its
    own field description for why, and algorithms/similarity.py's module
    docstring for the empirical verification.

    link_threshold/review_band_low are also given here as platform
    defaults, but a run's own generated.C11.RunManifest.parameters
    ("Free-form key/number map: linkThreshold, reviewBandLow, topK, etc.")
    is the per-run override mechanism for those two scalars specifically -
    see algorithms/clustering.py::run_clustering()."""

    weights: dict[str, float] = Field(
        default_factory=lambda: {
            "lexical": 0.27,
            "embedding": 0.05,
            "type": 0.20,
            "constraints": 0.27,
            "context": 0.21,
        },
        description="A documented, deliberate departure from the spec's "
        "own literal 0.20/0.30/0.15/0.20/0.15 (Section 9.3). This PoC's "
        "embedding provider (substrate/embedding.py::mock_embed, "
        "unchanged since Increment 5 - a deterministic SHA256 hash of "
        "the whole normalised text, carrying no semantic content by its "
        "own docstring's admission) makes cosine(a.embedding, "
        "b.embedding) pure noise: two attributes that are IDENTICAL in "
        "every other feature still cap out at score 0.70 under the "
        "spec's own weights, strictly below LINK_THRESHOLD=0.72 - no "
        "real pair could ever auto-link. Weight is discounted to 0.05 "
        "(not 0.0 - cosine still contributes something, just not "
        "reliably) and redistributed across the other four features in "
        "their original relative proportions. A deployment wiring a "
        "real embedding model should raise this back toward the spec's "
        "0.30 - this is a PoC default, not a claim about the algorithm "
        "in general.",
    )
    type_compatibility: list[TypeCompatibilityEntry] = Field(
        default_factory=lambda: [
            TypeCompatibilityEntry(a="string", b="string", score=1.0),
            TypeCompatibilityEntry(a="date", b="dateTime", score=0.85),
            TypeCompatibilityEntry(a="string", b="date", score=0.55),
            TypeCompatibilityEntry(a="decimal", b="integer", score=0.70),
            TypeCompatibilityEntry(a="string", b="boolean", score=0.30),
            TypeCompatibilityEntry(a="object", b="string", score=0.10),
        ]
    )
    abbreviations: dict[str, str] = Field(
        default_factory=lambda: {
            "dt": "date",
            "dttm": "dateTime",
            "amt": "amount",
            "nbr": "number",
            "cd": "code",
            "ind": "indicator",
            "desc": "description",
            "ref": "reference",
            "no": "number",
            "qty": "quantity",
            "sinistre": "claim",
            "police": "policy",
        }
    )
    link_threshold: float = Field(default=0.72, ge=0.0, le=1.0)
    review_band_low: float = Field(default=0.55, ge=0.0, le=1.0)
    block_top_k: int = Field(default=25, gt=0)
    block_max_size: int = Field(default=40, gt=0)

    @model_validator(mode="after")
    def _review_band_not_above_link_threshold(self) -> "ClusteringConfig":
        if self.review_band_low > self.link_threshold:
            raise ValueError("clustering.review_band_low must not exceed clustering.link_threshold")
        return self


class ResolutionWeights(BaseModel):
    """Section 9.8's RESOLUTION dict, transcribed verbatim."""

    core: float = Field(default=1.0, ge=0.0, le=1.0)
    extension: float = Field(default=0.5, ge=0.0, le=1.0)
    gap: float = Field(default=0.0, ge=0.0, le=1.0)


class CoverageConfig(BaseModel):
    """Coverage computation (Section 9.8). region_floor/domain_target/
    resolution_weights are transcribed verbatim from the spec's own
    REGION_FLOOR/DOMAIN_TARGET/RESOLUTION constants - "configuration
    pinned in the run manifest" in spirit, the same reasoning
    ClusteringConfig's own weights/type_compatibility already follow."""

    region_floor: float = Field(default=0.85, ge=0.0, le=1.0)
    domain_target: float = Field(default=0.90, ge=0.0, le=1.0)
    resolution_weights: ResolutionWeights = Field(default_factory=ResolutionWeights)


def _require_hex64(value: str, field_label: str) -> None:
    if not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError(f"{field_label} must be exactly 64 lowercase hex characters (32 bytes)")


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
    lawful_basis: str = Field(
        default="legitimate-interest",
        description="Fixed platform-wide value for C3.lawfulBasis (Section "
        "5.5's append_ledger() requires it but the spec gives no "
        "per-artefact source for it anywhere - not in C2, not in the "
        "policy YAML). Not computed per-artefact; a single constant for "
        "this PoC's canonical-modelling purpose, matching the value "
        "already used in this repo's own Increment 1 C3 fixtures.",
    )
    ledger_signing_key: str = Field(
        description="PoC placeholder for the ledger's HMAC-SHA256 signing "
        "key (gate/ledger.py:sign() - the spec's own sign(signing_key, h) "
        "call site gives no algorithm at all, a builder decision). A "
        "single central key, distinct from the per-region tokenisation "
        "keys below. 64 lowercase hex characters (32 bytes).",
    )
    tokenisation_keys: dict[str, str] = Field(
        description="PoC stand-in for the spec's regional key store "
        "(Section 5.3: 'Region tokenisation keys live in the regional key "
        "store only. They MUST NOT be replicated to the central platform "
        "under any circumstance.') This repo has no such infrastructure, "
        "so these are committed PoC placeholder secrets in "
        "config/platform.yaml - exactly like storage.postgres_dsn's "
        "already-committed placeholder credential, NOT production key "
        "material. One 64-hex-char (32-byte) HMAC key per region.",
    )

    @model_validator(mode="after")
    def _keys_are_well_formed_hex(self) -> "EgressConfig":
        _require_hex64(self.ledger_signing_key, "egress.ledger_signing_key")
        for region in ("us", "uk", "eu"):
            key = self.tokenisation_keys.get(region)
            if key is None:
                raise ValueError(f"egress.tokenisation_keys is missing required region {region!r}")
            _require_hex64(key, f"egress.tokenisation_keys[{region!r}]")
        return self


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
    clustering: ClusteringConfig = Field(default_factory=ClusteringConfig)
    coverage: CoverageConfig = Field(default_factory=CoverageConfig)


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
