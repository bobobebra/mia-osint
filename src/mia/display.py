from __future__ import annotations

import ast
import json
import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit

_STRUCTURED_PREFIXES = ("{", "[", "(")
_BRAND_NAMES = {
    "behance": "Behance",
    "deviantart": "DeviantArt",
    "discord": "Discord",
    "dribbble": "Dribbble",
    "facebook": "Facebook",
    "flickr": "Flickr",
    "github": "GitHub",
    "gitlab": "GitLab",
    "instagram": "Instagram",
    "keybase": "Keybase",
    "lastfm": "Last.fm",
    "linkedin": "LinkedIn",
    "mastodon": "Mastodon",
    "medium": "Medium",
    "patreon": "Patreon",
    "picsart": "Picsart",
    "pinterest": "Pinterest",
    "producthunt": "Product Hunt",
    "reddit": "Reddit",
    "roblox": "Roblox",
    "sketchfab": "Sketchfab",
    "soundcloud": "SoundCloud",
    "sparkpeople": "SparkPeople",
    "stackoverflow": "Stack Overflow",
    "steamcommunity": "Steam Community",
    "telegram": "Telegram",
    "tiktok": "TikTok",
    "tinder": "Tinder",
    "twitch": "Twitch",
    "twitter": "X / Twitter",
    "vk": "VK",
    "x": "X",
    "youtube": "YouTube",
}


def looks_structured(value: object) -> bool:
    if isinstance(value, Mapping):
        return True
    if not isinstance(value, str):
        return False
    stripped = value.strip()
    return bool(stripped) and stripped.startswith(_STRUCTURED_PREFIXES)


def parse_mapping_hint(value: object) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return {str(key): item for key, item in value.items()}
    if not isinstance(value, str):
        return {}
    text = value.strip()
    if not text.startswith("{") or len(text) > 100_000:
        return {}
    for parser in (json.loads, ast.literal_eval):
        try:
            parsed = parser(text)
        except (TypeError, ValueError, SyntaxError, json.JSONDecodeError):
            continue
        if isinstance(parsed, Mapping):
            return {str(key): item for key, item in parsed.items()}
    return {}


def _brand_from_host(host: str) -> str | None:
    normalized = host.lower().strip(".")
    if not normalized:
        return None
    if normalized.startswith("www."):
        normalized = normalized[4:]

    special_hosts = {
        "gist.github.com": "GitHub Gist",
        "steamcommunity.com": "Steam Community",
        "stackoverflow.com": "Stack Overflow",
        "last.fm": "Last.fm",
    }
    if normalized in special_hosts:
        return special_hosts[normalized]

    labels = [label for label in normalized.split(".") if label]
    if len(labels) < 2:
        candidate = labels[0] if labels else ""
    else:
        candidate = labels[-2]
        if candidate in {"co", "com", "org", "net"} and len(labels) >= 3:
            candidate = labels[-3]

    if candidate in _BRAND_NAMES:
        return _BRAND_NAMES[candidate]
    words = [part for part in re.split(r"[-_]", candidate) if part]
    return " ".join(word.capitalize() for word in words) or None


def _host_from_url(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    if not candidate:
        return None
    if "://" not in candidate:
        candidate = f"https://{candidate}"
    try:
        return urlsplit(candidate).hostname
    except ValueError:
        return None


def friendly_site_name(
    site_hint: object,
    *,
    entry: Mapping[str, Any] | None = None,
    url: str | None = None,
    fallback: str = "Profile",
) -> str:
    """Return a compact human-readable site label from Maigret-style metadata."""

    entry = entry or {}
    metadata = parse_mapping_hint(site_hint)

    for source in (entry, metadata):
        for key in ("site", "site_name", "name", "title"):
            candidate = source.get(key)
            if isinstance(candidate, str):
                candidate = candidate.strip()
                if (
                    candidate
                    and not looks_structured(candidate)
                    and candidate.lower() != "unknown site"
                ):
                    return candidate

    if isinstance(site_hint, str):
        direct = site_hint.strip()
        if direct and not looks_structured(direct) and direct.lower() != "unknown site":
            return direct

    url_candidates: list[object] = [
        url,
        entry.get("url_user"),
        entry.get("profile_url"),
        entry.get("url"),
        metadata.get("urlMain"),
        metadata.get("url_main"),
        metadata.get("url"),
        metadata.get("urlProbe"),
        metadata.get("url_probe"),
    ]
    for candidate in url_candidates:
        host = _host_from_url(candidate)
        if host:
            brand = _brand_from_host(host)
            if brand:
                return brand

    tags = metadata.get("tags") or entry.get("tags")
    if isinstance(tags, list) and tags:
        first = str(tags[0]).strip()
        if first:
            return f"{first.capitalize()} profile"
    return fallback


def safe_finding_title(title: object, url: str | None = None, fallback: str = "Finding") -> str:
    """Defensively prevent serialized objects or markup from becoming report headings."""

    if isinstance(title, str):
        cleaned = " ".join(title.split()).strip()
        if cleaned and not looks_structured(cleaned):
            return cleaned
    return friendly_site_name(title, url=url, fallback=fallback)
