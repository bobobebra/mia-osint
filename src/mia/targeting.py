from __future__ import annotations

import ipaddress
import re
from pathlib import Path
from urllib.parse import urlsplit

from mia.exceptions import TargetError
from mia.models import TargetType

EMAIL_RE = re.compile(r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+$")
DOMAIN_RE = re.compile(
    r"^(?=.{1,253}\.?$)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}\.?$"
)
PHONE_RE = re.compile(r"^\+?[0-9][0-9 ()-]{5,20}$")
HASH_LENGTHS = {32: "md5/ntlm", 40: "sha1", 56: "sha224", 64: "sha256", 96: "sha384", 128: "sha512"}


def detect_target_type(target: str) -> TargetType:
    candidate = target.strip()
    if Path(candidate).expanduser().exists():
        return TargetType.FILE
    if EMAIL_RE.fullmatch(candidate):
        return TargetType.EMAIL
    if candidate.startswith(("http://", "https://")):
        parsed = urlsplit(candidate)
        if parsed.scheme in {"http", "https"} and parsed.hostname:
            return TargetType.URL
    try:
        ipaddress.ip_address(candidate)
        return TargetType.IP
    except ValueError:
        pass
    if DOMAIN_RE.fullmatch(candidate):
        return TargetType.DOMAIN
    compact_phone = re.sub(r"[ ()-]", "", candidate)
    if PHONE_RE.fullmatch(candidate) and (candidate.startswith("+") or len(compact_phone) >= 10):
        return TargetType.PHONE
    if len(candidate) in HASH_LENGTHS and re.fullmatch(r"[A-Fa-f0-9]+", candidate):
        return TargetType.HASH
    return TargetType.USERNAME


def validate_target(target: str, target_type: TargetType) -> str:
    candidate = target.strip()
    if not candidate:
        raise TargetError("target cannot be empty")
    if len(candidate) > 1024:
        raise TargetError("target is too long")
    if any(ord(char) < 32 for char in candidate):
        raise TargetError("target contains control characters")

    if target_type == TargetType.AUTO:
        target_type = detect_target_type(candidate)

    if target_type == TargetType.EMAIL and not EMAIL_RE.fullmatch(candidate):
        raise TargetError("invalid email address")
    if target_type == TargetType.URL:
        parsed = urlsplit(candidate)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise TargetError("invalid HTTP(S) URL")
    if target_type == TargetType.DOMAIN:
        try:
            candidate = candidate.rstrip(".").encode("idna").decode("ascii").lower()
        except UnicodeError as exc:
            raise TargetError("invalid internationalized domain") from exc
        if not DOMAIN_RE.fullmatch(candidate):
            raise TargetError("invalid domain name")
    if target_type == TargetType.IP:
        try:
            candidate = str(ipaddress.ip_address(candidate))
        except ValueError as exc:
            raise TargetError("invalid IP address") from exc
    if target_type == TargetType.PHONE:
        compact = re.sub(r"[ ()-]", "", candidate)
        if not re.fullmatch(r"\+?[0-9]{7,15}", compact):
            raise TargetError("invalid phone number")
        candidate = compact
    if target_type == TargetType.FILE:
        path = Path(candidate).expanduser()
        if not path.exists() or not path.is_file():
            raise TargetError(f"file does not exist: {path}")
        candidate = str(path.resolve())
    if target_type == TargetType.CERTIFICATE:
        compact = re.sub(r"[^A-Fa-f0-9]", "", candidate)
        if len(compact) not in {40, 64, 96, 128}:
            raise TargetError("certificate fingerprint must be a SHA-style hexadecimal fingerprint")
        candidate = compact.lower()
    if target_type == TargetType.HASH:
        if not re.fullmatch(r"[A-Fa-f0-9]{16,256}", candidate):
            raise TargetError("hash must be a hexadecimal string between 16 and 256 characters")
        candidate = candidate.lower()
    if (
        target_type
        in {TargetType.PERSON, TargetType.COMPANY, TargetType.ADDRESS, TargetType.LOCATION}
        and len(candidate) > 512
    ):
        raise TargetError("text target is too long")
    if target_type == TargetType.USERNAME:
        if any(char.isspace() for char in candidate):
            raise TargetError(
                "username targets cannot contain whitespace; use --type person for names"
            )
        if len(candidate) > 128:
            raise TargetError("username is too long")

    return candidate


def classify_and_validate(target: str, requested: TargetType) -> tuple[str, TargetType]:
    resolved_type = detect_target_type(target) if requested == TargetType.AUTO else requested
    return validate_target(target, resolved_type), resolved_type
