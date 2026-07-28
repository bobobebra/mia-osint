from __future__ import annotations

import re
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass
from urllib.parse import urlsplit

from mia.config import PivotConfig
from mia.models import MergedFinding, PivotCandidate, ScanResult, TargetType
from mia.targeting import EMAIL_RE, classify_and_validate

EMAIL_KEYS = {"email", "emails", "email_address", "email_addresses", "contact_email"}
DOMAIN_KEYS = {
    "domain",
    "domains",
    "hostname",
    "hostnames",
    "apex_domain",
    "subdomain",
    "subdomains",
}
IP_KEYS = {"ip", "ips", "ip_address", "ip_addresses", "address"}
PHONE_KEYS = {"phone", "phones", "phone_number", "telephone"}
USERNAME_KEYS = {"username", "usernames", "handle", "handles", "screen_name"}
HASH_KEYS = {"hash", "sha256", "sha1", "md5", "fingerprint"}

KIND_TYPES = {
    "username": TargetType.USERNAME,
    "email": TargetType.EMAIL,
    "email_account": TargetType.EMAIL,
    "domain": TargetType.DOMAIN,
    "subdomain": TargetType.DOMAIN,
    "lookalike_domain": TargetType.DOMAIN,
    "ip": TargetType.IP,
    "phone": TargetType.PHONE,
    "hash": TargetType.HASH,
    "certificate": TargetType.CERTIFICATE,
}


@dataclass(slots=True)
class PivotTask:
    candidate: PivotCandidate
    depth: int
    parent_scan_id: str | None


def _iter_values(value: object) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, (list, tuple, set)):
        for item in value:
            yield from _iter_values(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from _iter_values(item)


def _candidate(
    value: str,
    target_type: TargetType,
    finding: MergedFinding,
    reason: str,
) -> PivotCandidate | None:
    try:
        normalized, resolved = classify_and_validate(value, target_type)
    except Exception:
        return None
    return PivotCandidate(
        target=normalized,
        target_type=resolved,
        source_finding_key=finding.dedup_key,
        reason=reason,
        confidence=finding.confidence,
    )


def extract_pivots(result: ScanResult, config: PivotConfig) -> list[PivotCandidate]:
    pivots: list[PivotCandidate] = []
    seen: set[tuple[TargetType, str]] = {(result.target_type, result.target.lower())}

    def add(candidate: PivotCandidate | None) -> None:
        if candidate is None:
            return
        key = (candidate.target_type, candidate.target.lower())
        if key in seen or candidate.target_type not in config.allowed_types:
            return
        if candidate.confidence < config.min_confidence:
            return
        seen.add(key)
        pivots.append(candidate)

    for finding in result.findings:
        direct_type = KIND_TYPES.get(finding.kind)
        if direct_type:
            if finding.kind == "lookalike_domain" and not config.include_lookalike_domains:
                pass
            else:
                add(
                    _candidate(
                        finding.value, direct_type, finding, f"finding kind '{finding.kind}'"
                    )
                )

        for raw_key, raw_value in finding.attributes.items():
            key = raw_key.lower().replace("-", "_")
            target_type: TargetType | None = None
            if key in EMAIL_KEYS:
                target_type = TargetType.EMAIL
            elif key in DOMAIN_KEYS:
                target_type = TargetType.DOMAIN
            elif key in IP_KEYS:
                target_type = TargetType.IP
            elif key in PHONE_KEYS:
                target_type = TargetType.PHONE
            elif key in USERNAME_KEYS:
                target_type = TargetType.USERNAME
            elif key in HASH_KEYS:
                target_type = TargetType.HASH
            if not target_type:
                continue
            for value in _iter_values(raw_value):
                add(_candidate(value, target_type, finding, f"attribute '{raw_key}'"))

        # URLs are not pivoted to their platform host automatically. Only extract
        # explicit email/phone selectors from the URL itself.
        if finding.url:
            parsed = urlsplit(finding.url)
            for match in re.findall(
                r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+", parsed.path + "?" + parsed.query
            ):
                if EMAIL_RE.fullmatch(match):
                    add(_candidate(match, TargetType.EMAIL, finding, "email embedded in URL"))

    return pivots[: config.max_targets]


class PivotQueue:
    def __init__(self, config: PivotConfig) -> None:
        self.config = config
        self._queue: deque[PivotTask] = deque()
        self._visited: set[tuple[TargetType, str]] = set()

    def mark_visited(self, target: str, target_type: TargetType) -> None:
        self._visited.add((target_type, target.lower()))

    def enqueue(
        self,
        candidates: Iterable[PivotCandidate],
        *,
        depth: int,
        parent_scan_id: str | None,
    ) -> int:
        if depth > self.config.max_depth:
            return 0
        added = 0
        for candidate in candidates:
            key = (candidate.target_type, candidate.target.lower())
            if key in self._visited:
                continue
            if len(self._visited) >= self.config.max_targets:
                break
            self._visited.add(key)
            self._queue.append(PivotTask(candidate, depth, parent_scan_id))
            added += 1
        return added

    def pop(self) -> PivotTask | None:
        return self._queue.popleft() if self._queue else None

    def __bool__(self) -> bool:
        return bool(self._queue)
