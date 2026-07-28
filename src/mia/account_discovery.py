from __future__ import annotations

import re
import urllib.parse
from dataclasses import dataclass

from mia.graph import canonical_entity, confidence_label, stable_edge_id, stable_node_id
from mia.models import (
    ConfidenceFactor,
    DeepCaseSeed,
    EvidenceEdge,
    EvidenceEffect,
    EvidenceNode,
    ScanProfile,
    TargetType,
)
from mia.workspace import CaseWorkspace


@dataclass(frozen=True, slots=True)
class PublicProfileReference:
    platform: str
    username: str
    url: str


@dataclass(frozen=True, slots=True)
class UsernameVariant:
    username: str
    confidence: float
    reason: str


_HOST_PLATFORM = {
    "instagram.com": "instagram",
    "tiktok.com": "tiktok",
    "x.com": "x",
    "twitter.com": "x",
    "threads.net": "threads",
    "github.com": "github",
    "reddit.com": "reddit",
    "youtube.com": "youtube",
    "youtu.be": "youtube",
    "twitch.tv": "twitch",
    "pinterest.com": "pinterest",
    "snapchat.com": "snapchat",
    "facebook.com": "facebook",
    "fb.com": "facebook",
    "bsky.app": "bluesky",
    "t.me": "telegram",
    "telegram.me": "telegram",
    "vk.com": "vk",
    "roblox.com": "roblox",
    "steamcommunity.com": "steam",
    "soundcloud.com": "soundcloud",
}

_HOST_ALIASES = {
    "m.facebook.com": "facebook",
    "mobile.twitter.com": "x",
    "gist.github.com": "gist",
}

_RESERVED = {
    "about",
    "accounts",
    "ads",
    "api",
    "blog",
    "business",
    "careers",
    "channel",
    "channels",
    "contact",
    "developers",
    "discover",
    "download",
    "en",
    "explore",
    "feed",
    "features",
    "games",
    "help",
    "home",
    "i",
    "ideas",
    "intent",
    "jobs",
    "legal",
    "login",
    "marketplace",
    "news",
    "orgs",
    "p",
    "pin",
    "policies",
    "press",
    "privacy",
    "reel",
    "reels",
    "resources",
    "search",
    "settings",
    "share",
    "signup",
    "sponsors",
    "status",
    "stories",
    "support",
    "terms",
    "topics",
    "user",
    "users",
    "watch",
}

_USERNAME_RE = re.compile(r"^[^\s/?#&=]{1,128}$")


def _normalized_host(hostname: str | None) -> str:
    host = (hostname or "").casefold().rstrip(".")
    return host[4:] if host.startswith("www.") else host


def _platform_for_host(host: str) -> str | None:
    # Arbitrary subdomains are deliberately not accepted. Hosts such as
    # support.x.com and business.x.com contain documentation paths, not user
    # profiles, and previously produced high-confidence false accounts.
    return _HOST_PLATFORM.get(host) or _HOST_ALIASES.get(host)


def _clean_username(value: str) -> str:
    username = urllib.parse.unquote(value).strip().strip("/").lstrip("@").strip()
    return username if _USERNAME_RE.fullmatch(username) else ""


def parse_public_profile_url(value: str) -> PublicProfileReference | None:
    """Recognize a public social-profile URL and extract its platform handle."""

    candidate = value.strip()
    if not candidate.startswith(("http://", "https://")):
        return None
    parsed = urllib.parse.urlsplit(candidate)
    host = _normalized_host(parsed.hostname)
    platform = _platform_for_host(host)
    if not platform:
        return None
    parts = [urllib.parse.unquote(part) for part in parsed.path.split("/") if part]
    username = ""
    if platform in {"tiktok", "threads", "youtube"}:
        username = _clean_username(next((part for part in parts if part.startswith("@")), ""))
    elif platform == "reddit":
        if len(parts) >= 2 and parts[0].casefold() in {"u", "user"}:
            username = _clean_username(parts[1])
    elif platform == "bluesky":
        if len(parts) >= 2 and parts[0].casefold() == "profile":
            username = _clean_username(parts[1])
    elif platform == "roblox":
        # Roblox numeric profile URLs do not expose the canonical username.
        query_username = urllib.parse.parse_qs(parsed.query).get("username", [""])[0]
        if query_username:
            username = _clean_username(query_username)
        elif len(parts) >= 2 and parts[0].casefold() == "users" and not parts[1].isdigit():
            username = _clean_username(parts[1])
    elif platform == "steam":
        if len(parts) >= 2 and parts[0].casefold() == "id":
            username = _clean_username(parts[1])
    elif platform == "facebook" and parts and parts[0].casefold() == "profile.php":
        username = _clean_username(urllib.parse.parse_qs(parsed.query).get("id", [""])[0])
    elif parts:
        username = _clean_username(parts[0])
    if not username or username.casefold() in _RESERVED:
        return None
    canonical_query = ""
    if platform == "roblox" and parsed.path.casefold().rstrip("/") == "/user.aspx":
        canonical_query = urllib.parse.urlencode({"username": username})
    elif platform == "facebook" and parsed.path.casefold().rstrip("/") == "/profile.php":
        canonical_query = urllib.parse.urlencode({"id": username})
    canonical = urllib.parse.urlunsplit(
        (parsed.scheme.casefold(), host, parsed.path.rstrip("/"), canonical_query, "")
    )
    return PublicProfileReference(platform=platform, username=username, url=canonical)


def username_variants(username: str, *, limit: int = 8) -> list[UsernameVariant]:
    """Generate bounded, conservative handle variations for lead discovery."""

    original = _clean_username(username)
    if not original:
        return []
    variants: list[UsernameVariant] = []
    seen: set[str] = set()

    def add(value: str, confidence: float, reason: str) -> None:
        cleaned = _clean_username(value)
        key = cleaned.casefold()
        if not cleaned or key in seen or len(variants) >= limit:
            return
        seen.add(key)
        variants.append(UsernameVariant(cleaned, confidence, reason))

    add(original, 1.0, "Exact handle supplied by the user")
    collapsed = re.sub(r"[._-]+", "", original)
    if collapsed != original:
        add(collapsed, 0.62, "Removed common handle separators")
        add(re.sub(r"[._-]+", "_", original), 0.60, "Changed separators to underscores")
        add(re.sub(r"[._-]+", ".", original), 0.58, "Changed separators to periods")
    match = re.fullmatch(r"(.+?)[._-]?(\d{1,4})", original)
    if match and len(match.group(1)) >= 3:
        stem, digits = match.groups()
        add(stem, 0.48, "Removed a short trailing number")
        add(f"{stem}_{digits}", 0.55, "Separated the trailing number with an underscore")
        add(f"{stem}.{digits}", 0.53, "Separated the trailing number with a period")
    if "-" in original:
        add(original.replace("-", "_"), 0.57, "Changed hyphens to underscores")
    return variants


def expand_account_seeds(
    seeds: list[DeepCaseSeed],
    profile: ScanProfile,
    *,
    enabled: bool = True,
    generate_variants: bool = True,
    max_generated: int = 24,
) -> tuple[list[DeepCaseSeed], int]:
    """Add scan-ready handles from public profile URLs and cautious variants."""

    if not enabled:
        return seeds, 0
    variant_limits = {
        ScanProfile.QUICK: 1,
        ScanProfile.DEFAULT: 4,
        ScanProfile.DEEP: 8,
        ScanProfile.ALL: 10,
    }
    output = list(seeds)
    seen = {(seed.target_type, seed.target.casefold()) for seed in seeds}
    generated = 0

    def add(seed: DeepCaseSeed) -> None:
        nonlocal generated
        key = (seed.target_type, seed.target.casefold())
        if key in seen or generated >= max_generated:
            return
        seen.add(key)
        output.append(seed)
        generated += 1

    root_handles: list[tuple[str, DeepCaseSeed, str]] = []
    for seed in seeds:
        if seed.target_type == TargetType.URL:
            reference = parse_public_profile_url(seed.target)
            if reference:
                add(
                    DeepCaseSeed(
                        target=reference.username,
                        target_type=TargetType.USERNAME,
                        label=f"{reference.platform.title()} handle: @{reference.username}",
                        notes=(
                            f"Extracted from the supplied public {reference.platform} profile URL. "
                            "The handle is a discovery lead, not identity proof."
                        ),
                        confidence=min(seed.confidence, 0.98),
                        tags=sorted(set(seed.tags) | {"account-discovery", reference.platform}),
                        subject=seed.subject,
                    )
                )
                root_handles.append((reference.username, seed, reference.platform))
        elif seed.target_type == TargetType.USERNAME:
            root_handles.append((seed.target, seed, "unknown"))

    if not generate_variants:
        return output, generated
    for handle, source, _platform in root_handles:
        for variant in username_variants(handle, limit=variant_limits[profile])[1:]:
            add(
                DeepCaseSeed(
                    target=variant.username,
                    target_type=TargetType.USERNAME,
                    label=f"Possible handle variant: @{variant.username}",
                    notes=(
                        f"Generated from @{handle}: {variant.reason}. Search lead only; "
                        "requires independent profile evidence."
                    ),
                    confidence=variant.confidence,
                    tags=sorted(set(source.tags) | {"account-discovery", "generated-variant"}),
                    subject=source.subject,
                )
            )
    return output, generated


class LinkedAccountImporter:
    """Import only author-declared cross-profile identity links.

    Ordinary hyperlinks are never treated as identity evidence. Eligible links
    must come from an explicit ``rel=me``/JSON-LD ``sameAs`` declaration or a
    dedicated profile website field that directly names another supported
    public profile.
    """

    _ALLOWED_SOURCE_STATUSES = {"verified", "likely", "possible", "reachable"}
    _GENERATED_METHODS = {
        "explicit_public_profile_link",  # alpha 3/4 legacy value
        "declared_identity_link",
        "profile_website_field",
    }

    @staticmethod
    def _trusted_links(
        source: EvidenceNode,
    ) -> list[tuple[PublicProfileReference, str, float, str]]:
        status = str(source.attributes.get("verification_status") or "").casefold()
        if status and status not in LinkedAccountImporter._ALLOWED_SOURCE_STATUSES:
            return []
        verified = source.attributes.get("verified_profile")
        if not isinstance(verified, dict):
            return []

        candidates: list[tuple[str, str, float, str]] = []
        identity_links = verified.get("identity_links") or []
        if isinstance(identity_links, list):
            for raw in identity_links[:20]:
                candidates.append(
                    (
                        str(raw),
                        "declared_identity_link",
                        0.86,
                        "The source profile declares this account through rel=me or JSON-LD sameAs metadata.",
                    )
                )

        website = str(verified.get("website") or "").strip()
        if website:
            candidates.append(
                (
                    website,
                    "profile_website_field",
                    0.82,
                    "The source platform exposes this URL in its dedicated profile website field.",
                )
            )

        output: list[tuple[PublicProfileReference, str, float, str]] = []
        seen: set[str] = set()
        for raw, method, confidence, explanation in candidates:
            reference = parse_public_profile_url(raw)
            if not reference or reference.url in seen:
                continue
            seen.add(reference.url)
            output.append((reference, method, confidence, explanation))
        return output

    def import_from_verifications(self, workspace: CaseWorkspace) -> list[EvidenceNode]:
        existing_nodes = workspace.nodes()
        existing = {node.node_id for node in existing_nodes}
        added: list[EvidenceNode] = []
        edges: list[EvidenceEdge] = []
        accepted_node_ids: set[str] = set()

        for source in existing_nodes:
            for reference, method, link_confidence, explanation in self._trusted_links(source):
                canonical = canonical_entity("account", reference.url)
                node_id = stable_node_id(workspace.record.case_id, "account", canonical)
                if node_id == source.node_id:
                    continue
                accepted_node_ids.add(node_id)
                node = EvidenceNode(
                    node_id=node_id,
                    case_id=workspace.record.case_id,
                    entity_type="account",
                    label=f"{reference.platform.title()}: @{reference.username}",
                    value=reference.url,
                    canonical_value=canonical,
                    confidence=0.72,
                    confidence_label="Medium",
                    sources=["public-profile-link"],
                    evidence_refs=list(source.evidence_refs),
                    attributes={
                        "finding_kind": "profile",
                        "url": reference.url,
                        "platform": reference.platform,
                        "username": reference.username,
                        "discovery_method": method,
                        "association_confidence": link_confidence,
                        "association_reason": explanation,
                        "linked_from_node_id": source.node_id,
                    },
                )
                if node_id not in existing:
                    existing.add(node_id)
                    added.append(node)
                edge = EvidenceEdge(
                    edge_id=stable_edge_id(
                        workspace.record.case_id,
                        source.node_id,
                        node_id,
                        "links_to_account",
                    ),
                    case_id=workspace.record.case_id,
                    source_node_id=source.node_id,
                    target_node_id=node_id,
                    relation="links_to_account",
                    label="declares identity account",
                    confidence=link_confidence,
                    confidence_label=confidence_label(link_confidence),
                    reasons=[explanation],
                    factors=[
                        ConfidenceFactor(
                            factor_id=f"identity-link-{method}",
                            label=(
                                "Declared identity link"
                                if method == "declared_identity_link"
                                else "Profile website field"
                            ),
                            effect=EvidenceEffect.POSITIVE,
                            weight=link_confidence,
                            explanation=(
                                f"{explanation} This is association evidence, not standalone proof of identity."
                            ),
                            evidence_refs=[source.node_id, node_id],
                        )
                    ],
                    evidence_refs=list(source.evidence_refs),
                    attributes={"public_link": reference.url, "identity_link_method": method},
                )
                edges.append(edge)

        legacy_generated = [
            node.node_id
            for node in existing_nodes
            if str(node.attributes.get("discovery_method") or "") in self._GENERATED_METHODS
            and set(node.sources) <= {"public-profile-link"}
            and node.node_id not in accepted_node_ids
        ]
        workspace.delete_nodes(legacy_generated)
        if added:
            workspace.save_graph(added, [], [])
        workspace.replace_account_link_edges(edges)
        return added
