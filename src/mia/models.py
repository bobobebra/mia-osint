from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(UTC)


class TargetType(StrEnum):
    AUTO = "auto"
    USERNAME = "username"
    EMAIL = "email"
    DOMAIN = "domain"
    IP = "ip"
    PHONE = "phone"
    FILE = "file"
    HASH = "hash"
    PERSON = "person"
    URL = "url"
    CERTIFICATE = "certificate"
    COMPANY = "company"
    ADDRESS = "address"
    LOCATION = "location"


class AnalysisDepth(StrEnum):
    QUICK = "quick"
    STANDARD = "standard"
    THOROUGH = "thorough"
    EXHAUSTIVE = "exhaustive"


class VerificationStatus(StrEnum):
    DISCOVERED = "discovered"
    REACHABLE = "reachable"
    VERIFIED = "verified"
    LIKELY = "likely"
    POSSIBLE = "possible"
    PRIVATE = "private"
    SUSPENDED = "suspended"
    SOFT_404 = "soft_404"
    FALSE_POSITIVE = "false_positive"
    UNVERIFIED = "unverified"
    ERROR = "error"


class ReviewStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    DEFERRED = "deferred"


class ScanProfile(StrEnum):
    QUICK = "quick"
    DEFAULT = "default"
    DEEP = "deep"
    ALL = "all"

    @property
    def description(self) -> str:
        return {
            ScanProfile.QUICK: "Fast, low-cost checks with the smallest useful compatible tool set.",
            ScanProfile.DEFAULT: "Balanced everyday scan with good coverage and moderate runtime.",
            ScanProfile.DEEP: "Broader multi-tool investigation, including passive APIs where configured.",
            ScanProfile.ALL: "Every compatible enabled plugin with the broadest upstream settings.",
        }[self]


class FindingStatus(StrEnum):
    CONFIRMED = "confirmed"
    POSSIBLE = "possible"
    UNKNOWN = "unknown"
    NEGATIVE = "negative"


class PluginRunStatus(StrEnum):
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"
    SKIPPED = "skipped"
    UNAVAILABLE = "unavailable"
    TIMED_OUT = "timed_out"
    CACHED = "cached"


class CaseStatus(StrEnum):
    OPEN = "open"
    ARCHIVED = "archived"


class EvidenceEffect(StrEnum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"


class ToolStatus(BaseModel):
    plugin_id: str
    name: str
    available: bool
    executable: str | None = None
    version: str | None = None
    message: str = ""
    install_hint: str | None = None


class ConfidenceFactor(BaseModel):
    factor_id: str
    label: str
    effect: EvidenceEffect = EvidenceEffect.POSITIVE
    weight: float = Field(default=0.0, ge=-1.0, le=1.0)
    explanation: str
    evidence_refs: list[str] = Field(default_factory=list)


class Finding(BaseModel):
    plugin_id: str
    category: str
    kind: str
    title: str
    value: str
    url: str | None = None
    status: FindingStatus = FindingStatus.CONFIRMED
    source_confidence: float = Field(default=0.6, ge=0.0, le=1.0)
    attributes: dict[str, Any] = Field(default_factory=dict)
    evidence_path: str | None = None
    observed_at: datetime = Field(default_factory=utc_now)


class MergedFinding(BaseModel):
    dedup_key: str
    category: str
    kind: str
    title: str
    value: str
    url: str | None = None
    status: FindingStatus
    sources: list[str] = Field(default_factory=list)
    occurrences: int = 1
    confidence: float = Field(ge=0.0, le=1.0)
    confidence_label: str
    confidence_reasons: list[str] = Field(default_factory=list)
    confidence_factors: list[ConfidenceFactor] = Field(default_factory=list)
    attributes: dict[str, Any] = Field(default_factory=dict)
    evidence_paths: list[str] = Field(default_factory=list)
    observed_at: datetime = Field(default_factory=utc_now)


class ProcessResult(BaseModel):
    command: list[str]
    return_code: int | None = None
    started_at: datetime
    finished_at: datetime
    duration_seconds: float
    timed_out: bool = False
    stdout: str = ""
    stderr: str = ""
    stdout_path: str | None = None
    stderr_path: str | None = None
    output_truncated: bool = False


class PluginRunResult(BaseModel):
    plugin_id: str
    plugin_name: str
    status: PluginRunStatus
    started_at: datetime
    finished_at: datetime
    duration_seconds: float
    command: list[str] = Field(default_factory=list)
    return_code: int | None = None
    timed_out: bool = False
    output_truncated: bool = False
    raw_dir: str | None = None
    stdout_path: str | None = None
    stderr_path: str | None = None
    findings: list[Finding] = Field(default_factory=list)
    error: str | None = None
    warnings: list[str] = Field(default_factory=list)
    cached: bool = False
    cache_source_scan_id: str | None = None
    cache_age_seconds: float | None = None


class ScanResult(BaseModel):
    schema_version: str = "2.0"
    mia_version: str
    scan_id: str
    target: str
    target_type: TargetType
    profile: ScanProfile
    started_at: datetime = Field(default_factory=utc_now)
    finished_at: datetime | None = None
    duration_seconds: float | None = None
    output_dir: str
    requested_plugins: list[str] = Field(default_factory=list)
    plugin_runs: list[PluginRunResult] = Field(default_factory=list)
    findings: list[MergedFinding] = Field(default_factory=list)
    report_paths: dict[str, str] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    case_id: str | None = None
    case_name: str | None = None
    depth: int = 0
    parent_scan_id: str | None = None
    pivot_source_node_id: str | None = None

    @property
    def successful_plugins(self) -> int:
        return sum(
            run.status in {PluginRunStatus.SUCCESS, PluginRunStatus.PARTIAL, PluginRunStatus.CACHED}
            for run in self.plugin_runs
        )

    @property
    def failed_plugins(self) -> int:
        return sum(
            run.status
            in {PluginRunStatus.FAILED, PluginRunStatus.TIMED_OUT, PluginRunStatus.UNAVAILABLE}
            for run in self.plugin_runs
        )


class PluginContext(BaseModel):
    scan_id: str
    target: str
    target_type: TargetType
    profile: ScanProfile
    scan_dir: Path
    raw_dir: Path
    timeout_seconds: int
    extra_args: list[str] = Field(default_factory=list)


class CaseRecord(BaseModel):
    case_id: str
    name: str
    slug: str
    root_dir: str
    status: CaseStatus = CaseStatus.OPEN
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    initial_target: str | None = None
    initial_target_type: TargetType | None = None


class CaseAttachment(BaseModel):
    attachment_id: str
    case_id: str
    kind: str
    filename: str
    path: str
    sha256: str
    size_bytes: int = Field(ge=0)
    added_at: datetime = Field(default_factory=utc_now)
    note: str = ""


class EvidenceNode(BaseModel):
    node_id: str
    case_id: str
    entity_type: str
    label: str
    value: str
    canonical_value: str
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    confidence_label: str = "Low"
    sources: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    attributes: dict[str, Any] = Field(default_factory=dict)
    first_seen: datetime = Field(default_factory=utc_now)
    last_seen: datetime = Field(default_factory=utc_now)
    manual: bool = False


class EvidenceEdge(BaseModel):
    edge_id: str
    case_id: str
    source_node_id: str
    target_node_id: str
    relation: str
    label: str
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    confidence_label: str = "Low"
    reasons: list[str] = Field(default_factory=list)
    factors: list[ConfidenceFactor] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    attributes: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)


class TimelineEvent(BaseModel):
    event_id: str
    case_id: str
    title: str
    event_type: str
    occurred_at: datetime
    node_id: str | None = None
    source: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    attributes: dict[str, Any] = Field(default_factory=dict)


class PivotCandidate(BaseModel):
    target: str
    target_type: TargetType
    source_node_id: str | None = None
    source_finding_key: str | None = None
    reason: str
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


class CorrelationSuggestion(BaseModel):
    entity_type: str
    canonical_value: str
    case_ids: list[str]
    case_names: list[str]
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    reason: str


class AssistantStatement(BaseModel):
    text: str
    evidence_ids: list[str] = Field(default_factory=list)
    confidence: str = "medium"


class AssistantSummary(BaseModel):
    provider: str
    generated_at: datetime = Field(default_factory=utc_now)
    executive_summary: list[AssistantStatement] = Field(default_factory=list)
    notable_findings: list[AssistantStatement] = Field(default_factory=list)
    uncertainty_warnings: list[AssistantStatement] = Field(default_factory=list)
    suggested_next_steps: list[AssistantStatement] = Field(default_factory=list)
    rejected_ungrounded_statements: int = 0


class DeepCaseSeed(BaseModel):
    seed_id: str = ""
    target: str
    target_type: TargetType
    label: str = ""
    notes: str = ""
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    tags: list[str] = Field(default_factory=list)
    subject: str | None = None


class DeepCaseManifest(BaseModel):
    schema_version: str = "1.0"
    name: str
    workflow: str = "identity"
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    hypotheses: list[str] = Field(default_factory=list)
    notes: str = ""
    seeds: list[DeepCaseSeed] = Field(default_factory=list)


class ProfileVerification(BaseModel):
    verification_id: str
    case_id: str
    node_id: str
    url: str
    platform: str = "generic"
    status: VerificationStatus = VerificationStatus.UNVERIFIED
    score: float = Field(default=0.0, ge=0.0, le=1.0)
    reasons: list[str] = Field(default_factory=list)
    negative_reasons: list[str] = Field(default_factory=list)
    extracted: dict[str, Any] = Field(default_factory=dict)
    response_status: int | None = None
    final_url: str | None = None
    content_hash: str | None = None
    snapshot_path: str | None = None
    changed_fields: list[str] = Field(default_factory=list)
    verified_at: datetime = Field(default_factory=utc_now)
    error: str | None = None


class IdentityCluster(BaseModel):
    cluster_id: str
    case_id: str
    label: str
    node_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    confidence_label: str = "Low"
    reasons: list[str] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)


class ReviewTask(BaseModel):
    task_id: str
    case_id: str
    title: str
    description: str
    priority: str = "medium"
    status: ReviewStatus = ReviewStatus.PENDING
    evidence_ids: list[str] = Field(default_factory=list)
    recommended_action: str = ""
    created_at: datetime = Field(default_factory=utc_now)
    resolved_at: datetime | None = None
    resolution_note: str = ""


class AnalysisPass(BaseModel):
    role: str
    statements: list[AssistantStatement] = Field(default_factory=list)
    rejected_ungrounded_statements: int = 0


class InvestigationAnalysis(BaseModel):
    provider: str
    depth: AnalysisDepth = AnalysisDepth.STANDARD
    generated_at: datetime = Field(default_factory=utc_now)
    passes: list[AnalysisPass] = Field(default_factory=list)
    identity_assessments: list[AssistantStatement] = Field(default_factory=list)
    supporting_evidence: list[AssistantStatement] = Field(default_factory=list)
    contradictions: list[AssistantStatement] = Field(default_factory=list)
    false_positive_warnings: list[AssistantStatement] = Field(default_factory=list)
    recommended_workflow: list[AssistantStatement] = Field(default_factory=list)
    rejected_ungrounded_statements: int = 0
