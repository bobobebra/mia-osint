from __future__ import annotations

import contextlib
import os
from importlib.resources import files
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from mia.exceptions import ConfigurationError
from mia.models import AnalysisDepth, ScanProfile, TargetType
from mia.platform_support import platform_paths


class PathsConfig(BaseModel):
    output_dir: Path = Field(default_factory=lambda: platform_paths().reports_dir)
    cases_dir: Path = Field(default_factory=lambda: platform_paths().cases_dir)
    state_dir: Path = Field(default_factory=lambda: platform_paths().state_dir)
    log_dir: Path = Field(default_factory=lambda: platform_paths().log_dir)
    user_plugins_dir: Path = Field(default_factory=lambda: platform_paths().plugins_dir)

    @field_validator(
        "output_dir", "cases_dir", "state_dir", "log_dir", "user_plugins_dir", mode="before"
    )
    @classmethod
    def expand_path(cls, value: str | Path) -> Path:
        return Path(value).expanduser()

    @property
    def database_path(self) -> Path:
        return self.state_dir / "mia.db"

    @property
    def knowledge_database_path(self) -> Path:
        return self.state_dir / "knowledge.db"

    @property
    def cache_database_path(self) -> Path:
        return self.state_dir / "cache.db"


class CacheConfig(BaseModel):
    enabled: bool = True
    ttl_seconds: int = Field(default=86400, ge=0)
    api_ttl_seconds: int = Field(default=3600, ge=0)
    reuse_failed: bool = False


class ExecutionConfig(BaseModel):
    max_concurrency: int = Field(default=3, ge=1, le=32)
    max_capture_bytes: int = Field(default=50 * 1024 * 1024, ge=1024)
    default_timeout: int = Field(default=600, ge=1)
    keep_negative_findings: bool = False
    cache: CacheConfig = Field(default_factory=CacheConfig)


class ReportsConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    html: bool = True
    json_report: bool = Field(default=True, alias="json")
    text: bool = True
    markdown: bool = True
    create_latest_symlink: bool = True
    dashboard_raw_excerpt_bytes: int = Field(default=12000, ge=0, le=250000)


class ToolConfig(BaseModel):
    enabled: bool = True
    executable: str | None = None
    timeout: int | None = Field(default=None, ge=1)
    extra_args: list[str] = Field(default_factory=list)
    profile_args: dict[str, list[str]] = Field(default_factory=dict)
    install_hint: str | None = None

    @field_validator("executable")
    @classmethod
    def expand_executable(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return str(Path(value).expanduser()) if value.startswith(("~", ".", "/")) else value

    def args_for(self, profile: ScanProfile) -> list[str]:
        return [*self.profile_args.get(profile.value, []), *self.extra_args]


class ConfidenceConfig(BaseModel):
    default_source_reliability: dict[str, float] = Field(default_factory=dict)
    relationship_weights: dict[str, float] = Field(
        default_factory=lambda: {
            "same_email": 0.95,
            "same_phone": 0.95,
            "same_avatar_hash": 0.90,
            "same_domain": 0.84,
            "same_username": 0.70,
            "reported_by": 0.65,
            "contains": 0.60,
            "associated_with": 0.55,
        }
    )

    @field_validator("default_source_reliability", "relationship_weights")
    @classmethod
    def validate_scores(cls, value: dict[str, float]) -> dict[str, float]:
        for key, score in value.items():
            if not 0 <= score <= 1:
                raise ValueError(f"confidence score for {key} must be between 0 and 1")
        return value


class PivotConfig(BaseModel):
    enabled: bool = False
    max_depth: int = Field(default=2, ge=0, le=8)
    max_targets: int = Field(default=25, ge=1, le=500)
    min_confidence: float = Field(default=0.65, ge=0.0, le=1.0)
    child_profile: ScanProfile = ScanProfile.QUICK
    allowed_types: list[TargetType] = Field(
        default_factory=lambda: [
            TargetType.USERNAME,
            TargetType.EMAIL,
            TargetType.DOMAIN,
            TargetType.IP,
            TargetType.PHONE,
            TargetType.HASH,
            TargetType.CERTIFICATE,
        ]
    )
    include_lookalike_domains: bool = False


class VerificationConfig(BaseModel):
    enabled: bool = True
    timeout: int = Field(default=15, ge=1, le=120)
    max_profiles: int = Field(default=60, ge=1, le=1000)
    max_concurrency: int = Field(default=5, ge=1, le=32)
    max_response_bytes: int = Field(default=2 * 1024 * 1024, ge=4096, le=20 * 1024 * 1024)
    store_html: bool = False
    avatar_download: bool = True
    allow_private_networks: bool = False
    soft_404_phrases: list[str] = Field(
        default_factory=lambda: [
            "page not found",
            "user not found",
            "account not found",
            "this account doesn't exist",
            "this page isn't available",
            "profile unavailable",
        ]
    )


class IdentityConfig(BaseModel):
    cluster_threshold: float = Field(default=0.58, ge=0.0, le=1.0)
    strong_cluster_threshold: float = Field(default=0.78, ge=0.0, le=1.0)
    contradiction_threshold: float = Field(default=0.28, ge=0.0, le=1.0)
    username_only_cap: float = Field(default=0.38, ge=0.0, le=1.0)
    max_pairwise_profiles: int = Field(default=250, ge=2, le=2000)


class AccountDiscoveryConfig(BaseModel):
    enabled: bool = True
    generate_variants: bool = True
    max_generated_variants: int = Field(default=24, ge=0, le=200)
    follow_public_profile_links: bool = True
    max_link_hops: int = Field(default=2, ge=0, le=4)


class DeepCasesConfig(BaseModel):
    profile: ScanProfile = ScanProfile.DEEP
    verify_profiles: bool = True
    enable_pivoting: bool = True
    max_depth: int = Field(default=2, ge=0, le=8)
    max_targets: int = Field(default=75, ge=1, le=1000)
    analysis_depth: AnalysisDepth = AnalysisDepth.THOROUGH
    workflow: str = "identity"
    continue_on_seed_failure: bool = True


class WorkspaceConfig(BaseModel):
    auto_update_dashboard: bool = True
    auto_correlate: bool = True
    graph_max_nodes_in_dashboard: int = Field(default=1500, ge=10, le=10000)


class ApiServiceConfig(BaseModel):
    enabled: bool = False
    endpoint: str | None = None
    key_env: str | None = None
    key_env_aliases: list[str] = Field(default_factory=list)
    username_env: str | None = None
    organization_id: str | None = None
    timeout: int = Field(default=30, ge=1, le=300)
    extra_headers: dict[str, str] = Field(default_factory=dict)


class AssistantProviderConfig(BaseModel):
    endpoint: str
    model: str = ""
    thinking_level: str | None = None
    api_service: str | None = None
    timeout: int | None = Field(default=None, ge=1, le=600)
    requires_key: bool = True
    extra_headers: dict[str, str] = Field(default_factory=dict)


class AssistantConfig(BaseModel):
    provider: str = "local"
    enabled: bool = True
    # Legacy v4 alpha.1 OpenAI-compatible fields. They remain supported and are
    # used to seed the openai-compatible provider when no provider map is given.
    endpoint: str = "https://api.openai.com/v1/chat/completions"
    model: str = ""
    api_service: str = "assistant"
    timeout: int = Field(default=90, ge=1, le=600)
    send_raw_evidence: bool = False
    max_nodes: int = Field(default=200, ge=10, le=2000)
    max_context_items: int = Field(default=250, ge=10, le=5000)
    max_text_chars: int = Field(default=4000, ge=256, le=50000)
    analysis_depth: AnalysisDepth = AnalysisDepth.STANDARD
    max_passes: int = Field(default=8, ge=1, le=12)
    providers: dict[str, AssistantProviderConfig] = Field(default_factory=dict)

    @model_validator(mode="after")
    def ensure_provider_defaults(self) -> AssistantConfig:
        defaults = {
            "openai-compatible": AssistantProviderConfig(
                endpoint=self.endpoint,
                model=self.model,
                api_service=self.api_service,
                timeout=self.timeout,
                requires_key=True,
            ),
            "gemini": AssistantProviderConfig(
                endpoint="https://generativelanguage.googleapis.com/v1beta",
                model="",
                api_service="gemini",
                timeout=self.timeout,
                requires_key=True,
            ),
            "ollama": AssistantProviderConfig(
                endpoint="http://localhost:11434/api",
                model="",
                api_service="ollama",
                timeout=self.timeout,
                requires_key=False,
            ),
        }
        for name, settings in defaults.items():
            self.providers.setdefault(name, settings)
        # Preserve alpha.1 user configurations that only used the legacy
        # top-level OpenAI-compatible fields. The packaged default provider map
        # must not mask a model supplied by an older user config.
        openai = self.providers["openai-compatible"]
        legacy_default_endpoint = "https://api.openai.com/v1/chat/completions"
        if self.model.strip() and not openai.model.strip():
            openai.model = self.model
        if (
            self.endpoint.strip()
            and self.endpoint != legacy_default_endpoint
            and openai.endpoint == legacy_default_endpoint
        ):
            openai.endpoint = self.endpoint
        if self.api_service.strip() and openai.api_service == "assistant":
            openai.api_service = self.api_service
        if self.timeout != 90 and openai.timeout == 90:
            openai.timeout = self.timeout
        return self

    def settings(self, provider: str) -> AssistantProviderConfig:
        normalized = provider.strip().lower()
        aliases = {
            "openai": "openai-compatible",
            "google": "gemini",
            "google-gemini": "gemini",
            "ollama-local": "ollama",
        }
        normalized = aliases.get(normalized, normalized)
        try:
            return self.providers[normalized]
        except KeyError as exc:
            supported = ", ".join(["local", *sorted(self.providers)])
            raise ValueError(
                f"unknown assistant provider: {provider}; supported providers: {supported}"
            ) from exc


class AppConfig(BaseModel):
    paths: PathsConfig = Field(default_factory=PathsConfig)
    execution: ExecutionConfig = Field(default_factory=ExecutionConfig)
    reports: ReportsConfig = Field(default_factory=ReportsConfig)
    pivoting: PivotConfig = Field(default_factory=PivotConfig)
    verification: VerificationConfig = Field(default_factory=VerificationConfig)
    identity: IdentityConfig = Field(default_factory=IdentityConfig)
    account_discovery: AccountDiscoveryConfig = Field(default_factory=AccountDiscoveryConfig)
    deep_cases: DeepCasesConfig = Field(default_factory=DeepCasesConfig)
    workspaces: WorkspaceConfig = Field(default_factory=WorkspaceConfig)
    assistant: AssistantConfig = Field(default_factory=AssistantConfig)
    profiles: dict[str, list[str]] = Field(default_factory=dict)
    tools: dict[str, ToolConfig] = Field(default_factory=dict)
    apis: dict[str, ApiServiceConfig] = Field(default_factory=dict)
    confidence: ConfidenceConfig = Field(default_factory=ConfidenceConfig)
    loaded_from: Path | None = None

    @model_validator(mode="after")
    def ensure_profiles_and_apis(self) -> AppConfig:
        for profile in ScanProfile:
            self.profiles.setdefault(profile.value, ["*"])
        defaults = {
            "shodan": ("https://api.shodan.io", "MIA_SHODAN_API_KEY", []),
            "virustotal": (
                "https://www.virustotal.com/api/v3",
                "MIA_VIRUSTOTAL_API_KEY",
                [],
            ),
            "hibp": ("https://haveibeenpwned.com/api/v3", "MIA_HIBP_API_KEY", []),
            "securitytrails": (
                "https://api.securitytrails.com/v1",
                "MIA_SECURITYTRAILS_API_KEY",
                [],
            ),
            "censys": (
                "https://api.platform.censys.io/v3",
                "MIA_CENSYS_API_KEY",
                [],
            ),
            "intelx": ("https://2.intelx.io", "MIA_INTELX_API_KEY", []),
            "assistant": (
                self.assistant.endpoint,
                "MIA_ASSISTANT_API_KEY",
                ["OPENAI_API_KEY"],
            ),
            "gemini": (
                "https://generativelanguage.googleapis.com/v1beta",
                "GEMINI_API_KEY",
                ["GOOGLE_API_KEY", "MIA_GEMINI_API_KEY"],
            ),
            "ollama": (
                "http://localhost:11434/api",
                "OLLAMA_API_KEY",
                ["MIA_OLLAMA_API_KEY"],
            ),
        }
        for service, (endpoint, env_name, aliases) in defaults.items():
            existing = self.apis.setdefault(service, ApiServiceConfig())
            if existing.endpoint is None:
                existing.endpoint = endpoint
            if existing.key_env is None:
                existing.key_env = env_name
            if not existing.key_env_aliases:
                existing.key_env_aliases = aliases
        return self

    def tool(self, plugin_id: str) -> ToolConfig:
        return self.tools.get(plugin_id, ToolConfig())

    def api(self, service: str) -> ApiServiceConfig:
        return self.apis.get(service, ApiServiceConfig())

    def enabled_for_profile(self, plugin_id: str, profile: ScanProfile) -> bool:
        configured = self.profiles.get(profile.value, ["*"])
        return "*" in configured or plugin_id in configured

    def ensure_directories(self) -> None:
        for path in (
            self.paths.output_dir,
            self.paths.cases_dir,
            self.paths.state_dir,
            self.paths.log_dir,
            self.paths.user_plugins_dir,
        ):
            path.mkdir(parents=True, exist_ok=True, mode=0o700)
            with contextlib.suppress(OSError):
                path.chmod(0o700)


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        content = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except FileNotFoundError as exc:
        raise ConfigurationError(f"configuration file not found: {path}") from exc
    except yaml.YAMLError as exc:
        raise ConfigurationError(f"invalid YAML in {path}: {exc}") from exc
    if not isinstance(content, dict):
        raise ConfigurationError(f"configuration root must be a mapping: {path}")
    return content


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def default_config_path() -> Path:
    return Path(str(files("mia.data").joinpath("default_config.yaml")))


def user_config_path() -> Path:
    env_path = os.getenv("MIA_CONFIG")
    if env_path:
        return Path(env_path).expanduser()
    return platform_paths().config_dir / "config.yaml"


def load_config(explicit_path: Path | None = None) -> AppConfig:
    data = _load_yaml(default_config_path())
    selected_path: Path | None = None

    if explicit_path is not None:
        selected_path = explicit_path.expanduser()
        data = _deep_merge(data, _load_yaml(selected_path))
    else:
        candidate = user_config_path()
        if candidate.exists():
            selected_path = candidate
            data = _deep_merge(data, _load_yaml(candidate))

    if output_dir := os.getenv("MIA_OUTPUT_DIR"):
        data = _deep_merge(data, {"paths": {"output_dir": output_dir}})
    if state_dir := os.getenv("MIA_STATE_DIR"):
        data = _deep_merge(data, {"paths": {"state_dir": state_dir}})
    if cases_dir := os.getenv("MIA_CASES_DIR"):
        data = _deep_merge(data, {"paths": {"cases_dir": cases_dir}})

    try:
        config = AppConfig.model_validate(data)
    except Exception as exc:
        raise ConfigurationError(f"configuration validation failed: {exc}") from exc
    config.loaded_from = selected_path
    config.ensure_directories()
    return config


def initialize_user_config(destination: Path | None = None, force: bool = False) -> Path:
    destination = (destination or user_config_path()).expanduser()
    if destination.exists() and not force:
        raise ConfigurationError(f"configuration already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    destination.write_text(default_config_path().read_text(encoding="utf-8"), encoding="utf-8")
    with contextlib.suppress(OSError):
        destination.chmod(0o600)
    return destination
