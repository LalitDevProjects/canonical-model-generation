"""
Configuration Management (Section 15)

Handles configuration for environments, feature flags, and system settings.
Uses YAML for configuration and environment variables for overrides.
"""

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings


class Environment(str, Enum):
    """Deployment environments."""
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


class LLMProvider(str, Enum):
    """Supported LLM providers for agents."""
    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    LOCAL = "local"


class StorageBackend(str, Enum):
    """Supported storage backends."""
    FILESYSTEM = "filesystem"
    POSTGRESQL = "postgresql"
    CLOUD_STORAGE = "cloud_storage"


class LoggingConfig(BaseModel):
    """Logging configuration."""
    level: str = Field(default="INFO")
    format: str = Field(default="json")
    output: str = Field(default="stdout")  # stdout, file, cloud
    include_traceback: bool = Field(default=True)


class LLMConfig(BaseModel):
    """LLM/Agent configuration."""
    provider: LLMProvider = Field(default=LLMProvider.ANTHROPIC)
    
    # API credentials (from environment)
    api_key: Optional[str] = Field(default=None, description="Loaded from environment")
    
    # Model selection
    primary_model: str = Field(default="claude-3-opus")
    fallback_model: Optional[str] = Field(default=None)
    
    # Rate limiting and costs
    max_tokens_per_minute: int = Field(default=50000)
    max_monthly_cost_usd: float = Field(default=10000.0)
    
    # Timeouts and retries
    timeout_seconds: int = Field(default=60)
    max_retries: int = Field(default=3)
    retry_backoff_base: float = Field(default=2.0)
    
    # Context window
    max_context_tokens: int = Field(default=100000)
    
    # Temperature and sampling
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    top_p: float = Field(default=0.9, ge=0.0, le=1.0)


class StorageConfig(BaseModel):
    """Storage configuration."""
    backend: StorageBackend = Field(default=StorageBackend.FILESYSTEM)
    
    # Base paths for filesystem
    data_directory: str = Field(default="./data")
    cache_directory: str = Field(default="./data/cache")
    
    # Database configuration
    db_connection_string: Optional[str] = Field(default=None)
    db_pool_size: int = Field(default=10)
    
    # Cloud storage (if applicable)
    cloud_bucket: Optional[str] = Field(default=None)
    cloud_region: Optional[str] = Field(default=None)


class IngestionConfig(BaseModel):
    """Ingestion pipeline configuration."""
    # Processing limits
    batch_size: int = Field(default=100)
    max_attribute_per_source: int = Field(default=10000)
    
    # Type normalization
    infer_code_contracts: bool = Field(default=True)
    handle_xsd: bool = Field(default=True)
    handle_wsdl: bool = Field(default=True)
    handle_openapi: bool = Field(default=True)
    
    # Incremental support
    support_incremental: bool = Field(default=True)
    
    # Content filtering
    min_content_length_bytes: int = Field(default=100)
    max_content_length_bytes: int = Field(default=10_000_000)


class AlgorithmConfig(BaseModel):
    """Core algorithm configuration."""
    # Blocking
    blocking_enabled: bool = Field(default=True)
    
    # Similarity scoring
    similarity_threshold: float = Field(default=0.7, ge=0.0, le=1.0)
    
    # Clustering
    clustering_algorithm: str = Field(default="hierarchical")  # hierarchical, kmeans, agglomerative
    cluster_min_size: int = Field(default=2)
    
    # ACORD alignment
    acord_alignment_threshold: float = Field(default=0.6, ge=0.0, le=1.0)
    use_fuzzy_matching: bool = Field(default=True)


class SanitisationConfig(BaseModel):
    """Data sanitisation configuration."""
    enabled: bool = Field(default=True)
    
    # PII detection
    detect_pii: bool = Field(default=True)
    pii_removal_strategy: str = Field(default="masking")  # masking, redaction, removal
    
    # Governance
    enforce_classification: bool = Field(default=True)
    min_classification_level: str = Field(default="internal")
    
    # Retention
    data_retention_days: int = Field(default=90)


class ObservabilityConfig(BaseModel):
    """Observability configuration."""
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    
    # Metrics
    metrics_enabled: bool = Field(default=True)
    metrics_port: int = Field(default=8000)
    
    # Tracing
    tracing_enabled: bool = Field(default=False)
    trace_sample_rate: float = Field(default=0.1, ge=0.0, le=1.0)
    
    # Cost tracking
    track_costs: bool = Field(default=True)


class ConcurrencyConfig(BaseModel):
    """Concurrency and performance configuration."""
    # Parallelism
    max_workers: int = Field(default=4)
    max_concurrent_llm_calls: int = Field(default=2)
    
    # Rate limiting
    global_rate_limit_per_second: int = Field(default=100)
    
    # Timeouts
    task_timeout_seconds: int = Field(default=300)


class PlatformSettings(BaseSettings):
    """
    Main platform settings (Section 15.1).
    
    Loads from:
    1. Environment variables (highest priority)
    2. YAML configuration file
    3. Hard-coded defaults
    """
    
    # Environment
    environment: Environment = Field(default=Environment.DEVELOPMENT)
    
    # Core components
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    
    # Pipeline stages
    ingestion: IngestionConfig = Field(default_factory=IngestionConfig)
    algorithms: AlgorithmConfig = Field(default_factory=AlgorithmConfig)
    sanitisation: SanitisationConfig = Field(default_factory=SanitisationConfig)
    
    # Cross-cutting
    observability: ObservabilityConfig = Field(default_factory=ObservabilityConfig)
    concurrency: ConcurrencyConfig = Field(default_factory=ConcurrencyConfig)
    
    # Feature flags (Section 15.3)
    feature_flags: Dict[str, bool] = Field(
        default_factory=lambda: {
            "enable_llm_agents": True,
            "enable_incremental_ingestion": False,
            "enable_fuzzy_matching": True,
            "enable_audit_logging": True,
            "enable_cost_controls": True,
            "enable_checkpoint_validation": True,
        }
    )
    
    # Custom configuration
    custom_config: Dict[str, Any] = Field(default_factory=dict)
    
    class Config:
        env_nested_delimiter = "__"
        env_file = ".env"
        use_enum_values = True
    
    @property
    def is_production(self) -> bool:
        """Check if running in production."""
        return self.environment == Environment.PRODUCTION
    
    @property
    def is_development(self) -> bool:
        """Check if running in development."""
        return self.environment == Environment.DEVELOPMENT
    
    def feature_enabled(self, feature_name: str) -> bool:
        """Check if a feature flag is enabled."""
        return self.feature_flags.get(feature_name, False)
    
    def get_custom(self, key: str, default: Any = None) -> Any:
        """Get custom configuration value."""
        return self.custom_config.get(key, default)


# Global configuration instance
_settings: Optional[PlatformSettings] = None


def get_settings() -> PlatformSettings:
    """Get the global platform settings instance."""
    global _settings
    if _settings is None:
        _settings = PlatformSettings()
    return _settings


def reload_settings() -> None:
    """Reload settings from configuration sources."""
    global _settings
    _settings = None


__all__ = [
    "Environment",
    "LLMProvider",
    "StorageBackend",
    "LoggingConfig",
    "LLMConfig",
    "StorageConfig",
    "IngestionConfig",
    "AlgorithmConfig",
    "SanitisationConfig",
    "ObservabilityConfig",
    "ConcurrencyConfig",
    "PlatformSettings",
    "get_settings",
    "reload_settings",
]
