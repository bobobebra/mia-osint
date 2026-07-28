from __future__ import annotations

import math
import re
from collections import defaultdict
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from mia.config import ConfidenceConfig
from mia.display import safe_finding_title
from mia.models import (
    ConfidenceFactor,
    EvidenceEffect,
    Finding,
    FindingStatus,
    MergedFinding,
)

TRACKING_QUERY_KEYS = {
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "ref",
    "ref_src",
    "source",
}


def canonicalize_url(value: str) -> str:
    candidate = value.strip()
    if not re.match(r"^[a-z][a-z0-9+.-]*://", candidate, flags=re.I):
        candidate = f"https://{candidate}"
    parts = urlsplit(candidate)
    scheme = parts.scheme.lower() or "https"
    hostname = (parts.hostname or "").lower().rstrip(".")
    if hostname.startswith("www."):
        hostname = hostname[4:]
    port = parts.port
    netloc = hostname
    if port and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        netloc = f"{hostname}:{port}"
    path = re.sub(r"/{2,}", "/", parts.path or "/")
    if path != "/":
        path = path.rstrip("/")
    query = [
        (key, item)
        for key, item in parse_qsl(parts.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in TRACKING_QUERY_KEYS
    ]
    return urlunsplit((scheme, netloc, path, urlencode(sorted(query)), ""))


def dedup_key(finding: Finding) -> str:
    if finding.url:
        return f"url:{canonicalize_url(finding.url)}"
    if finding.kind in {"email", "email_account"}:
        return f"{finding.kind}:{finding.value.strip().lower()}"
    if finding.kind in {"domain", "dns", "whois"}:
        return f"{finding.kind}:{finding.value.strip().lower().rstrip('.')}"
    if finding.kind == "phone":
        return f"phone:{re.sub(r'[^0-9+]', '', finding.value)}"
    return f"{finding.kind}:{finding.title.strip().lower()}:{finding.value.strip().lower()}"


def _confidence_label(score: float) -> str:
    if score >= 0.85:
        return "High"
    if score >= 0.65:
        return "Medium"
    if score >= 0.40:
        return "Low"
    return "Very low"


def _merge_attributes(findings: list[Finding]) -> dict[str, object]:
    merged: dict[str, object] = {}
    conflicts: dict[str, list[object]] = defaultdict(list)
    for finding in findings:
        for key, value in finding.attributes.items():
            if key not in merged:
                merged[key] = value
            elif merged[key] != value and value not in conflicts[key]:
                conflicts[key].append(value)
    if conflicts:
        merged["conflicts"] = dict(conflicts)
    return merged


def _score_group(
    findings: list[Finding], confidence: ConfidenceConfig
) -> tuple[float, list[str], list[ConfidenceFactor]]:
    best_by_source: dict[str, float] = {}
    for finding in findings:
        reliability = confidence.default_source_reliability.get(finding.plugin_id, 0.6)
        effective = (finding.source_confidence + reliability) / 2
        best_by_source[finding.plugin_id] = max(
            best_by_source.get(finding.plugin_id, 0.0), effective
        )

    direct_kinds = {"metadata", "dns", "whois", "hash"}
    if findings[0].kind in direct_kinds and len(best_by_source) == 1:
        combined = min(0.98, max(best_by_source.values()) + 0.08)
    else:
        combined = 1 - math.prod(1 - value for value in best_by_source.values())
        combined = min(combined, 0.97)

    statuses = {finding.status for finding in findings}
    highest = max(best_by_source.values())
    reasons = [f"Highest source assessment: {highest:.0%}"]
    factors = [
        ConfidenceFactor(
            factor_id="source-reliability",
            label="Source assessment",
            weight=round(highest, 4),
            explanation=f"The strongest source assessed this result at {highest:.0%}.",
            evidence_refs=sorted({item.evidence_path for item in findings if item.evidence_path}),
        )
    ]
    if len(best_by_source) > 1:
        reasons.append(f"Corroborated by {len(best_by_source)} independent plugins")
        factors.append(
            ConfidenceFactor(
                factor_id="independent-corroboration",
                label="Independent corroboration",
                weight=min(0.30, 0.10 * (len(best_by_source) - 1)),
                explanation=f"{len(best_by_source)} independent plugins reported the same normalized entity.",
                evidence_refs=sorted(
                    {item.evidence_path for item in findings if item.evidence_path}
                ),
            )
        )
    else:
        reasons.append("Single-source result; manual verification is recommended")
        factors.append(
            ConfidenceFactor(
                factor_id="single-source",
                label="Single source",
                effect=EvidenceEffect.NEUTRAL,
                weight=0.0,
                explanation="Only one plugin reported this entity, so independent verification is still needed.",
                evidence_refs=sorted(
                    {item.evidence_path for item in findings if item.evidence_path}
                ),
            )
        )
    if FindingStatus.POSSIBLE in statuses or FindingStatus.UNKNOWN in statuses:
        combined = max(0.0, combined - 0.10)
        reasons.append("At least one source marked the result as uncertain")
        factors.append(
            ConfidenceFactor(
                factor_id="source-uncertainty",
                label="Source uncertainty",
                effect=EvidenceEffect.NEGATIVE,
                weight=-0.10,
                explanation="At least one source marked the result possible or unknown.",
            )
        )
    if FindingStatus.NEGATIVE in statuses and len(statuses) > 1:
        combined = max(0.0, combined - 0.15)
        reasons.append("Sources contained conflicting positive and negative evidence")
        factors.append(
            ConfidenceFactor(
                factor_id="source-conflict",
                label="Conflicting evidence",
                effect=EvidenceEffect.NEGATIVE,
                weight=-0.15,
                explanation="The source set contained both positive and negative evidence.",
            )
        )
    return round(combined, 4), reasons, factors


def merge_findings(
    findings: list[Finding],
    confidence: ConfidenceConfig,
    keep_negative: bool = False,
) -> list[MergedFinding]:
    grouped: dict[str, list[Finding]] = defaultdict(list)
    for finding in findings:
        if finding.status == FindingStatus.NEGATIVE and not keep_negative:
            continue
        grouped[dedup_key(finding)].append(finding)

    merged: list[MergedFinding] = []
    for key, group in grouped.items():
        group.sort(key=lambda item: item.source_confidence, reverse=True)
        primary = group[0]
        score, reasons, factors = _score_group(group, confidence)
        sources = sorted({item.plugin_id for item in group})
        statuses = {item.status for item in group}
        status = (
            FindingStatus.CONFIRMED
            if FindingStatus.CONFIRMED in statuses
            else FindingStatus.POSSIBLE
            if FindingStatus.POSSIBLE in statuses
            else primary.status
        )
        merged.append(
            MergedFinding(
                dedup_key=key,
                category=primary.category,
                kind=primary.kind,
                title=safe_finding_title(primary.title, primary.url),
                value=primary.value,
                url=canonicalize_url(primary.url) if primary.url else None,
                status=status,
                sources=sources,
                occurrences=len(group),
                confidence=score,
                confidence_label=_confidence_label(score),
                confidence_reasons=reasons,
                confidence_factors=factors,
                attributes=_merge_attributes(group),
                evidence_paths=sorted({item.evidence_path for item in group if item.evidence_path}),
            )
        )
    return sorted(
        merged,
        key=lambda item: (-item.confidence, item.category.lower(), item.title.lower()),
    )
