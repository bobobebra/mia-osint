from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from mia.models import AnalysisDepth, ReviewStatus, ScanProfile, TargetType


class SeedInput(BaseModel):
    target: str = Field(min_length=1)
    target_type: TargetType
    label: str = ""
    notes: str = ""
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    tags: list[str] = Field(default_factory=list)
    subject: str | None = None

    @field_validator("target", "label", "notes", "subject", mode="before")
    @classmethod
    def strip_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class DeepCaseRequest(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str = ""
    workflow: str = "identity"
    tags: list[str] = Field(default_factory=list)
    hypotheses: list[str] = Field(default_factory=list)
    notes: str = ""
    seeds: list[SeedInput] = Field(min_length=1)
    case_identifier: str | None = None
    profile: ScanProfile = ScanProfile.DEEP
    verify_profiles: bool = True
    enable_pivoting: bool = True
    max_depth: int = Field(default=2, ge=0, le=8)
    max_targets: int = Field(default=75, ge=1, le=1000)
    include_tools: list[str] = Field(default_factory=list)
    exclude_tools: list[str] = Field(default_factory=list)
    use_cache: bool = True


class NoteRequest(BaseModel):
    text: str = Field(min_length=1, max_length=100_000)


class ReviewResolutionRequest(BaseModel):
    status: ReviewStatus
    note: str = Field(default="", max_length=10_000)


class AnalyzeRequest(BaseModel):
    provider: str | None = None
    model: str | None = None
    endpoint: str | None = None
    confirm_external_cost: bool = False
    depth: AnalysisDepth = AnalysisDepth.THOROUGH
    thinking_level: Literal["minimal", "low", "medium", "high"] | None = None


class GuidedReviewRequest(BaseModel):
    use_ai: bool = False
    provider: Literal["local", "openai-compatible", "gemini", "ollama"] | None = None
    confirm_external_cost: bool = False
    depth: AnalysisDepth = AnalysisDepth.THOROUGH
    thinking_level: Literal["minimal", "low", "medium", "high"] | None = "high"


class PackageOperationRequest(BaseModel):
    action: Literal["install", "update", "uninstall"]
    tools: list[str] = Field(min_length=1)
    include_mixed: bool = False
    remove_system: bool = False


class ProviderConfigRequest(BaseModel):
    provider: Literal["local", "openai-compatible", "gemini", "ollama"]
    model: str | None = None
    endpoint: str | None = None
    thinking_level: Literal["minimal", "low", "medium", "high"] | None = None
    set_default: bool = True


class ApiKeyRequest(BaseModel):
    service: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    value: str = Field(min_length=1, max_length=20_000)
