from __future__ import annotations

import asyncio
import hashlib
import io
import ipaddress
import json
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import UTC, datetime
from html.parser import HTMLParser
from typing import Any

from mia.config import AppConfig
from mia.graph import stable_edge_id
from mia.models import (
    ConfidenceFactor,
    EvidenceEdge,
    EvidenceEffect,
    EvidenceNode,
    IdentityCluster,
    ProfileVerification,
    ReviewTask,
    TimelineEvent,
    VerificationStatus,
)
from mia.utils import atomic_write_json, atomic_write_text
from mia.workspace import CaseWorkspace


class _ProfileHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self._in_title = False
        self.meta: dict[str, str] = {}
        self.links: list[str] = []
        self.identity_links: list[str] = []
        self.json_ld_blocks: list[str] = []
        self.text_parts: list[str] = []
        self._ignored_depth = 0
        self._json_ld_depth = 0
        self._json_ld_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lowered = tag.lower()
        data = {key.lower(): value or "" for key, value in attrs}
        if (
            lowered == "script"
            and data.get("type", "").split(";", 1)[0].strip().lower() == "application/ld+json"
        ):
            self._json_ld_depth += 1
            self._json_ld_parts = []
            return
        if lowered in {"script", "style", "noscript", "template"}:
            self._ignored_depth += 1
            return
        if lowered == "title":
            self._in_title = True
        if lowered == "meta":
            key = data.get("property") or data.get("name")
            content = data.get("content")
            if key and content:
                self.meta[key.lower()] = content.strip()
        if lowered == "a" and data.get("href"):
            self.links.append(data["href"].strip())
        if lowered in {"a", "link"} and data.get("href"):
            rel = {item.casefold() for item in data.get("rel", "").split()}
            if "me" in rel:
                self.identity_links.append(data["href"].strip())

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()
        if lowered == "script" and self._json_ld_depth:
            self._json_ld_depth = max(0, self._json_ld_depth - 1)
            payload = "".join(self._json_ld_parts).strip()
            if payload:
                self.json_ld_blocks.append(payload)
            self._json_ld_parts = []
            return
        if lowered in {"script", "style", "noscript", "template"}:
            self._ignored_depth = max(0, self._ignored_depth - 1)
            return
        if lowered == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._json_ld_depth:
            self._json_ld_parts.append(data)
            return
        if self._ignored_depth:
            return
        cleaned = " ".join(data.split())
        if not cleaned:
            return
        if self._in_title:
            self.title = f"{self.title} {cleaned}".strip()
        if len(" ".join(self.text_parts)) < 50_000:
            self.text_parts.append(cleaned)


class ProfileVerifier:
    """Passively validate candidate profile URLs and extract bounded public metadata."""

    PROFILE_TYPES = {"profile", "web_profile", "account", "social_profile"}

    def __init__(self, config: AppConfig) -> None:
        self.config = config

    @staticmethod
    def _username_from_url(url: str) -> str:
        parsed = urllib.parse.urlsplit(url)
        query = urllib.parse.parse_qs(parsed.query)
        for key in ("username", "user", "id"):
            if query.get(key):
                return str(query[key][0]).strip("/@")
        pieces = [piece for piece in parsed.path.split("/") if piece]
        if not pieces:
            return ""
        candidate = pieces[-1].lstrip("@")
        if candidate.lower() in {"user", "users", "profile", "u", "member"} and len(pieces) > 1:
            candidate = pieces[-2].lstrip("@")
        return candidate

    @staticmethod
    def _platform(url: str) -> str:
        host = (urllib.parse.urlsplit(url).hostname or "").lower()
        if host.startswith("www."):
            host = host[4:]
        if "github.com" in host:
            return "github"
        if "roblox.com" in host:
            return "roblox"
        if "tiktok.com" in host:
            return "tiktok"
        if "reddit.com" in host:
            return "reddit"
        return host or "generic"

    async def verify_case(self, workspace: CaseWorkspace) -> list[ProfileVerification]:
        nodes = [
            node
            for node in workspace.nodes()
            if (
                node.entity_type in self.PROFILE_TYPES
                or node.attributes.get("finding_kind")
                in {"profile", "web_profile", "email_account"}
            )
            and str(node.attributes.get("url") or node.value).startswith(("http://", "https://"))
        ]
        return await self.verify_nodes(workspace, nodes)

    async def verify_nodes(
        self, workspace: CaseWorkspace, nodes: list[EvidenceNode]
    ) -> list[ProfileVerification]:
        """Verify a bounded set of candidate nodes without rechecking the whole case."""

        eligible = [
            node
            for node in nodes
            if (
                node.entity_type in self.PROFILE_TYPES
                or node.attributes.get("finding_kind")
                in {"profile", "web_profile", "email_account"}
            )
            and str(node.attributes.get("url") or node.value).startswith(("http://", "https://"))
        ][: self.config.verification.max_profiles]
        semaphore = asyncio.Semaphore(self.config.verification.max_concurrency)

        async def one(node: EvidenceNode) -> ProfileVerification:
            async with semaphore:
                return await self.verify_node(workspace, node)

        results = await asyncio.gather(*(one(node) for node in eligible)) if eligible else []
        for result in results:
            workspace.save_verification(result)
        return results

    async def verify_node(
        self, workspace: CaseWorkspace, node: EvidenceNode
    ) -> ProfileVerification:
        url = str(node.attributes.get("url") or node.value)
        platform = self._platform(url)
        verification_id = (
            "verify-"
            + hashlib.sha256(
                f"{workspace.record.case_id}|{node.node_id}|{url}|{datetime.now(UTC).isoformat(timespec='microseconds')}".encode()
            ).hexdigest()[:20]
        )
        try:
            if platform == "github":
                result = await self._verify_github(workspace, node, verification_id, url)
            elif platform == "roblox":
                result = await self._verify_roblox(workspace, node, verification_id, url)
            elif platform == "reddit":
                result = await self._verify_reddit(workspace, node, verification_id, url)
            else:
                result = await self._verify_generic(workspace, node, verification_id, url, platform)
        except Exception as exc:  # network/parsing failures must not abort a case
            result = ProfileVerification(
                verification_id=verification_id,
                case_id=workspace.record.case_id,
                node_id=node.node_id,
                url=url,
                platform=platform,
                status=VerificationStatus.ERROR,
                score=0.05,
                reasons=[],
                negative_reasons=["Verification request failed"],
                error=str(exc)[:1000],
            )
        self._apply_to_node(workspace, node, result)
        return result

    async def _verify_github(
        self, workspace: CaseWorkspace, node: EvidenceNode, verification_id: str, url: str
    ) -> ProfileVerification:
        username = self._username_from_url(url)
        if not username:
            return await self._verify_generic(workspace, node, verification_id, url, "github")
        api = f"https://api.github.com/users/{urllib.parse.quote(username, safe='')}"
        status, final_url, headers, body = await self._fetch(
            api, accept="application/vnd.github+json"
        )
        if status == 404:
            return self._result(
                workspace,
                node,
                verification_id,
                url,
                "github",
                status,
                VerificationStatus.FALSE_POSITIVE,
                0.02,
                [],
                ["GitHub API returned 404 for the claimed username"],
                {},
                final_url,
                body,
            )
        if not 200 <= status < 300:
            return self._result(
                workspace,
                node,
                verification_id,
                url,
                "github",
                status,
                VerificationStatus.PRIVATE
                if status in {401, 403, 429}
                else VerificationStatus.UNVERIFIED,
                0.2,
                [],
                [f"GitHub API returned HTTP {status}; the candidate could not be verified"],
                {},
                final_url,
                body,
            )
        payload = json.loads(body.decode("utf-8", errors="replace")) if body else {}
        if not isinstance(payload, dict) or not payload.get("login"):
            return self._result(
                workspace,
                node,
                verification_id,
                url,
                "github",
                status,
                VerificationStatus.UNVERIFIED,
                0.2,
                [],
                ["GitHub API did not return a concrete user object"],
                {},
                final_url,
                body,
            )
        extracted = {
            "username": payload.get("login"),
            "display_name": payload.get("name"),
            "bio": payload.get("bio"),
            "location": payload.get("location"),
            "website": payload.get("blog"),
            "avatar_url": payload.get("avatar_url"),
            "created_at": payload.get("created_at"),
            "updated_at": payload.get("updated_at"),
            "public_repos": payload.get("public_repos"),
            "followers": payload.get("followers"),
            "following": payload.get("following"),
            "numeric_id": payload.get("id"),
            "account_type": payload.get("type"),
        }
        await self._enrich_avatar(extracted)
        reasons = ["GitHub API returned a concrete user object"]
        if str(payload.get("login", "")).casefold() == username.casefold():
            reasons.append("The returned login exactly matches the candidate username")
        score = 0.96 if len(reasons) > 1 else 0.9
        return self._result(
            workspace,
            node,
            verification_id,
            url,
            "github",
            status,
            VerificationStatus.VERIFIED,
            score,
            reasons,
            [],
            extracted,
            final_url,
            body,
        )

    async def _verify_roblox(
        self, workspace: CaseWorkspace, node: EvidenceNode, verification_id: str, url: str
    ) -> ProfileVerification:
        username = self._username_from_url(url)
        if not username:
            return await self._verify_generic(workspace, node, verification_id, url, "roblox")
        endpoint = "https://users.roblox.com/v1/usernames/users"
        status, final_url, headers, body = await self._fetch(
            endpoint,
            method="POST",
            json_body={"usernames": [username], "excludeBannedUsers": False},
            accept="application/json",
        )
        if not 200 <= status < 300:
            return self._result(
                workspace,
                node,
                verification_id,
                url,
                "roblox",
                status,
                VerificationStatus.PRIVATE
                if status in {401, 403, 429}
                else VerificationStatus.UNVERIFIED,
                0.2,
                [],
                [
                    f"Roblox username API returned HTTP {status}; the candidate could not be verified"
                ],
                {},
                final_url,
                body,
            )
        payload = json.loads(body.decode("utf-8", errors="replace")) if body else {}
        matches = payload.get("data", []) if isinstance(payload, dict) else []
        if not matches:
            return self._result(
                workspace,
                node,
                verification_id,
                url,
                "roblox",
                status,
                VerificationStatus.FALSE_POSITIVE,
                0.02,
                [],
                ["Roblox username lookup returned no user"],
                {},
                final_url,
                body,
            )
        match = matches[0]
        user_id = match.get("id")
        detail_status, detail_url, _, detail_body = await self._fetch(
            f"https://users.roblox.com/v1/users/{user_id}", accept="application/json"
        )
        detail = json.loads(detail_body.decode("utf-8", errors="replace")) if detail_body else {}
        if not 200 <= detail_status < 300 or not isinstance(detail, dict) or not detail.get("name"):
            return self._result(
                workspace,
                node,
                verification_id,
                url,
                "roblox",
                detail_status,
                VerificationStatus.UNVERIFIED,
                0.25,
                ["Roblox resolved the candidate to a numeric user ID"],
                ["Roblox did not return a complete public user object"],
                {"numeric_id": user_id, "username": match.get("name")},
                detail_url,
                detail_body,
            )
        extracted = {
            "username": detail.get("name") or match.get("name"),
            "display_name": detail.get("displayName") or match.get("displayName"),
            "description": detail.get("description"),
            "created_at": detail.get("created"),
            "numeric_id": user_id,
            "is_banned": detail.get("isBanned"),
            "has_verified_badge": detail.get("hasVerifiedBadge"),
        }
        # Roblox detail endpoints do not include the thumbnail URL; keep the numeric ID for later adapters.
        reasons = ["Roblox public username API returned a numeric user ID"]
        if str(extracted.get("username", "")).casefold() == username.casefold():
            reasons.append("The canonical Roblox username exactly matches the candidate")
        status_value = (
            VerificationStatus.SUSPENDED
            if extracted.get("is_banned")
            else VerificationStatus.VERIFIED
        )
        negatives = ["Roblox reports the account as banned"] if extracted.get("is_banned") else []
        return self._result(
            workspace,
            node,
            verification_id,
            url,
            "roblox",
            detail_status,
            status_value,
            0.94,
            reasons,
            negatives,
            extracted,
            detail_url,
            detail_body,
        )

    async def _verify_reddit(
        self, workspace: CaseWorkspace, node: EvidenceNode, verification_id: str, url: str
    ) -> ProfileVerification:
        username = self._username_from_url(url)
        if not username:
            return await self._verify_generic(workspace, node, verification_id, url, "reddit")
        endpoint = f"https://www.reddit.com/user/{urllib.parse.quote(username, safe='')}/about.json"
        status, final_url, _, body = await self._fetch(endpoint, accept="application/json")
        if status in {404, 410}:
            return self._result(
                workspace,
                node,
                verification_id,
                url,
                "reddit",
                status,
                VerificationStatus.FALSE_POSITIVE,
                0.02,
                [],
                [f"Reddit returned HTTP {status} for the claimed username"],
                {},
                final_url,
                body,
            )
        payload = json.loads(body.decode("utf-8", errors="replace")) if body else {}
        data = payload.get("data", {}) if isinstance(payload, dict) else {}
        if not isinstance(data, dict) or not data.get("name"):
            return self._result(
                workspace,
                node,
                verification_id,
                url,
                "reddit",
                status,
                VerificationStatus.UNVERIFIED,
                0.2,
                [],
                ["Reddit did not return a concrete public account object"],
                {},
                final_url,
                body,
            )
        created = data.get("created_utc")
        created_at = None
        if isinstance(created, (int, float)):
            created_at = datetime.fromtimestamp(created, UTC).isoformat()
        extracted = {
            "username": data.get("name"),
            "display_name": data.get("subreddit", {}).get("title")
            if isinstance(data.get("subreddit"), dict)
            else None,
            "description": data.get("subreddit", {}).get("public_description")
            if isinstance(data.get("subreddit"), dict)
            else None,
            "avatar_url": data.get("snoovatar_img") or data.get("icon_img"),
            "created_at": created_at,
            "link_karma": data.get("link_karma"),
            "comment_karma": data.get("comment_karma"),
            "is_suspended": data.get("is_suspended"),
            "has_verified_email": data.get("has_verified_email"),
            "numeric_id": data.get("id"),
        }
        await self._enrich_avatar(extracted)
        reasons = ["Reddit public API returned a concrete account object"]
        if str(data.get("name", "")).casefold() == username.casefold():
            reasons.append("The canonical Reddit username exactly matches the candidate")
        suspended = bool(data.get("is_suspended"))
        return self._result(
            workspace,
            node,
            verification_id,
            url,
            "reddit",
            status,
            VerificationStatus.SUSPENDED if suspended else VerificationStatus.VERIFIED,
            0.9 if suspended else 0.95,
            reasons,
            ["Reddit reports the account as suspended"] if suspended else [],
            extracted,
            final_url,
            body,
        )

    async def _verify_generic(
        self,
        workspace: CaseWorkspace,
        node: EvidenceNode,
        verification_id: str,
        url: str,
        platform: str,
    ) -> ProfileVerification:
        status, final_url, headers, body = await self._fetch(
            url, accept="text/html,application/xhtml+xml"
        )
        text = body.decode("utf-8", errors="replace")
        parser = _ProfileHTMLParser()
        parser.feed(text)
        username = self._username_from_url(url)
        reasons: list[str] = []
        negatives: list[str] = []
        verification_status = VerificationStatus.UNVERIFIED
        score = 0.2
        if status in {404, 410}:
            verification_status = VerificationStatus.FALSE_POSITIVE
            score = 0.01
            negatives.append(f"The server returned HTTP {status}")
        elif status in {401, 403}:
            verification_status = VerificationStatus.PRIVATE
            score = 0.45
            negatives.append(
                f"The profile could not be inspected because the server returned HTTP {status}"
            )
        elif 200 <= status < 300:
            reasons.append(f"The candidate page returned HTTP {status}")
            score = 0.48
            verification_status = VerificationStatus.REACHABLE
            visible_and_meta = " ".join(
                [
                    parser.title,
                    *parser.text_parts,
                    *parser.meta.values(),
                ]
            ).casefold()
            soft_phrase = next(
                (
                    phrase
                    for phrase in self.config.verification.soft_404_phrases
                    if phrase.casefold() in visible_and_meta
                ),
                None,
            )
            if soft_phrase:
                verification_status = VerificationStatus.SOFT_404
                score = 0.08
                negatives.append(f"The page contains a soft-404 indicator: {soft_phrase!r}")
            else:
                visible_text = " ".join(parser.text_parts).casefold()
                identity_text = " ".join(
                    value
                    for value in (
                        parser.title,
                        parser.meta.get("og:title", ""),
                        parser.meta.get("description", ""),
                        parser.meta.get("og:description", ""),
                        parser.meta.get("profile:username", ""),
                    )
                    if value
                ).casefold()
                blocked_phrase = next(
                    (
                        phrase
                        for phrase in (
                            "verify you are human",
                            "captcha",
                            "log in to continue",
                            "sign in to continue",
                            "access denied",
                        )
                        if phrase in visible_text
                    ),
                    None,
                )
                signals: list[str] = []
                if username and username.casefold() in identity_text:
                    signals.append("candidate username appears in profile title or metadata")
                if username and username.casefold() in visible_text:
                    signals.append("candidate username appears in visible page text")
                if parser.meta.get("profile:username", "").casefold() == username.casefold():
                    signals.append("profile metadata explicitly names the candidate username")
                canonical = parser.meta.get("og:url", final_url)
                if (
                    username
                    and username.casefold() in urllib.parse.urlsplit(canonical).path.casefold()
                ):
                    signals.append("canonical profile URL contains the candidate username")
                if blocked_phrase:
                    verification_status = VerificationStatus.PRIVATE
                    score = 0.35
                    negatives.append(f"The page could not be inspected fully: {blocked_phrase}")
                elif len(signals) >= 2:
                    reasons.extend(signals)
                    score = 0.7
                    verification_status = VerificationStatus.LIKELY
                elif signals:
                    reasons.extend(signals)
                    negatives.append("Only one profile-specific signal was available")
                    score = 0.46
                    verification_status = VerificationStatus.POSSIBLE
                else:
                    negatives.append(
                        "No profile-specific username signal was found in visible text or metadata"
                    )
                    score = 0.28
                    verification_status = VerificationStatus.REACHABLE
            original_host = (urllib.parse.urlsplit(url).hostname or "").casefold()
            final_host = (urllib.parse.urlsplit(final_url).hostname or "").casefold()
            if original_host and final_host and original_host != final_host:
                negatives.append("The request redirected to a different host")
                score = min(score, 0.3)
        else:
            negatives.append(f"Unexpected HTTP status {status}")
            verification_status = VerificationStatus.UNVERIFIED
            score = 0.15
        extracted = {
            "username": username or None,
            "display_name": parser.meta.get("og:title") or parser.title or None,
            "bio": parser.meta.get("description") or parser.meta.get("og:description") or None,
            "avatar_url": parser.meta.get("og:image") or parser.meta.get("twitter:image") or None,
            "canonical_url": parser.meta.get("og:url") or final_url,
            "page_title": parser.title or None,
            "external_links": self._external_links(final_url, parser.links)[:20],
            "identity_links": self._identity_links(final_url, parser, username=username)[:12],
            "content_type": headers.get("content-type"),
            "platform_limitations": (
                "TikTok frequently returns login walls or anti-bot pages; this generic verification "
                "cannot establish account ownership."
                if platform == "tiktok"
                else None
            ),
        }
        await self._enrich_avatar(extracted)
        return self._result(
            workspace,
            node,
            verification_id,
            url,
            platform,
            status,
            verification_status,
            score,
            reasons,
            negatives,
            extracted,
            final_url,
            body,
        )

    @staticmethod
    def _external_links(base_url: str, links: list[str]) -> list[str]:
        base_host = (urllib.parse.urlsplit(base_url).hostname or "").casefold()
        output: list[str] = []
        for raw in links:
            absolute = urllib.parse.urljoin(base_url, raw)
            parsed = urllib.parse.urlsplit(absolute)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                continue
            if parsed.hostname.casefold() == base_host:
                continue
            normalized = urllib.parse.urlunsplit(
                (parsed.scheme, parsed.netloc, parsed.path, parsed.query, "")
            )
            if normalized not in output:
                output.append(normalized)
        return output

    @staticmethod
    def _identity_links(
        base_url: str, parser: _ProfileHTMLParser, *, username: str = ""
    ) -> list[str]:
        """Return only author-declared identity links, never arbitrary page anchors."""

        candidates = list(parser.identity_links)
        normalized_username = re.sub(r"[^a-z0-9]", "", username.casefold())

        def collect_same_as(value: Any) -> None:
            if isinstance(value, dict):
                same_as = next(
                    (item for key, item in value.items() if key.casefold() == "sameas"), None
                )
                if same_as is not None:
                    identity_fields = [
                        value.get("url"),
                        value.get("name"),
                        value.get("alternateName"),
                        value.get("identifier"),
                        value.get("@id"),
                    ]
                    identity_blob = re.sub(
                        r"[^a-z0-9]",
                        "",
                        " ".join(str(item or "") for item in identity_fields).casefold(),
                    )
                    if not normalized_username or normalized_username in identity_blob:
                        if isinstance(same_as, str):
                            candidates.append(same_as)
                        elif isinstance(same_as, list):
                            candidates.extend(
                                str(entry) for entry in same_as if isinstance(entry, str)
                            )
                for key, item in value.items():
                    if key.casefold() != "sameas":
                        collect_same_as(item)
            elif isinstance(value, list):
                for item in value:
                    collect_same_as(item)

        for block in parser.json_ld_blocks[:20]:
            try:
                collect_same_as(json.loads(block))
            except (json.JSONDecodeError, TypeError, ValueError):
                continue

        output: list[str] = []
        for raw in candidates:
            absolute = urllib.parse.urljoin(base_url, str(raw))
            parsed = urllib.parse.urlsplit(absolute)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                continue
            normalized = urllib.parse.urlunsplit(
                (
                    parsed.scheme.casefold(),
                    parsed.netloc.casefold(),
                    parsed.path.rstrip("/"),
                    parsed.query,
                    "",
                )
            )
            if normalized not in output:
                output.append(normalized)
        return output

    async def _enrich_avatar(self, extracted: dict[str, Any]) -> None:
        avatar_url = str(extracted.get("avatar_url") or "").strip()
        if not self.config.verification.avatar_download or not avatar_url.startswith(
            ("http://", "https://")
        ):
            return
        try:
            status, _, headers, body = await self._fetch(avatar_url, accept="image/*")
            if not (200 <= status < 300) or not body:
                return
            extracted["avatar_hash"] = hashlib.sha256(body).hexdigest()
            extracted["avatar_content_type"] = headers.get("content-type")
            try:
                from PIL import Image  # optional vision extra

                image = Image.open(io.BytesIO(body)).convert("L").resize((9, 8))
                pixels = list(image.getdata())
                bits = []
                for y in range(8):
                    row = pixels[y * 9 : (y + 1) * 9]
                    bits.extend(row[x] > row[x + 1] for x in range(8))
                value = 0
                for bit in bits:
                    value = (value << 1) | int(bit)
                extracted["avatar_dhash"] = f"{value:016x}"
            except (ImportError, OSError, ValueError):
                pass
        except Exception:
            return

    def _result(
        self,
        workspace: CaseWorkspace,
        node: EvidenceNode,
        verification_id: str,
        url: str,
        platform: str,
        status: int,
        verification_status: VerificationStatus,
        score: float,
        reasons: list[str],
        negatives: list[str],
        extracted: dict[str, Any],
        final_url: str,
        body: bytes,
    ) -> ProfileVerification:
        digest = hashlib.sha256(body).hexdigest() if body else None
        snapshot_dir = workspace.snapshots_dir / node.node_id
        snapshot_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        previous = workspace.latest_verification(node.node_id)
        changed: list[str] = []
        if previous:
            keys = set(previous.extracted) | set(extracted)
            changed = sorted(
                key for key in keys if previous.extracted.get(key) != extracted.get(key)
            )
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        snapshot_path = snapshot_dir / f"{stamp}.json"
        snapshot_payload = {
            "url": url,
            "final_url": final_url,
            "response_status": status,
            "platform": platform,
            "verification_status": verification_status.value,
            "score": score,
            "reasons": reasons,
            "negative_reasons": negatives,
            "extracted": extracted,
            "content_hash": digest,
            "captured_at": datetime.now(UTC).isoformat(),
        }
        atomic_write_json(snapshot_path, snapshot_payload)
        if (
            self.config.verification.store_html
            and body
            and platform not in {"github", "roblox", "reddit"}
        ):
            html_path = snapshot_dir / f"{stamp}.html"
            atomic_write_text(html_path, body.decode("utf-8", errors="replace"))
            extracted["html_snapshot_path"] = str(html_path)
        return ProfileVerification(
            verification_id=verification_id,
            case_id=workspace.record.case_id,
            node_id=node.node_id,
            url=url,
            platform=platform,
            status=verification_status,
            score=score,
            reasons=reasons,
            negative_reasons=negatives,
            extracted={k: v for k, v in extracted.items() if v is not None and v != "" and v != []},
            response_status=status,
            final_url=final_url,
            content_hash=digest,
            snapshot_path=str(snapshot_path),
            changed_fields=changed,
        )

    async def _fetch(
        self,
        url: str,
        *,
        method: str = "GET",
        json_body: dict[str, Any] | None = None,
        accept: str = "*/*",
    ) -> tuple[int, str, dict[str, str], bytes]:
        return await asyncio.to_thread(self._fetch_sync, url, method, json_body, accept)

    def _fetch_sync(
        self,
        url: str,
        method: str,
        json_body: dict[str, Any] | None,
        accept: str,
    ) -> tuple[int, str, dict[str, str], bytes]:
        self._validate_fetch_url(url)
        data = json.dumps(json_body).encode() if json_body is not None else None
        headers = {
            "User-Agent": "MIA-OSINT/4.1 profile verifier (+lawful passive verification)",
            "Accept": accept,
        }
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        verifier = self

        class _ValidatedRedirectHandler(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, response_headers, newurl):  # type: ignore[no-untyped-def]
                verifier._validate_fetch_url(newurl)
                return super().redirect_request(req, fp, code, msg, response_headers, newurl)

        opener = urllib.request.build_opener(_ValidatedRedirectHandler())
        try:
            with opener.open(request, timeout=self.config.verification.timeout) as response:
                body = response.read(self.config.verification.max_response_bytes + 1)
                if len(body) > self.config.verification.max_response_bytes:
                    body = body[: self.config.verification.max_response_bytes]
                return (
                    int(response.status),
                    response.geturl(),
                    {key.lower(): value for key, value in response.headers.items()},
                    body,
                )
        except urllib.error.HTTPError as exc:
            body = exc.read(self.config.verification.max_response_bytes)
            return (
                int(exc.code),
                exc.geturl(),
                {key.lower(): value for key, value in exc.headers.items()},
                body,
            )

    def _validate_fetch_url(self, url: str) -> None:
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("profile verification only permits HTTP(S) URLs with a hostname")
        if parsed.username or parsed.password:
            raise ValueError("profile verification does not permit credentials embedded in URLs")
        if self.config.verification.allow_private_networks:
            return
        hostname = parsed.hostname.rstrip(".").casefold()
        if hostname == "localhost" or hostname.endswith((".localhost", ".local", ".internal")):
            raise ValueError("profile verification blocked a local/private hostname")
        try:
            addresses = {
                item[4][0]
                for item in socket.getaddrinfo(
                    hostname,
                    parsed.port or (443 if parsed.scheme == "https" else 80),
                    type=socket.SOCK_STREAM,
                )
            }
        except socket.gaierror as exc:
            raise ValueError(f"profile hostname could not be resolved: {hostname}") from exc
        if not addresses:
            raise ValueError(f"profile hostname resolved to no addresses: {hostname}")
        for raw in addresses:
            address = ipaddress.ip_address(raw.split("%", 1)[0])
            if (
                address.is_private
                or address.is_loopback
                or address.is_link_local
                or address.is_multicast
                or address.is_reserved
                or address.is_unspecified
            ):
                raise ValueError(
                    f"profile verification blocked non-public address {address} for {hostname}"
                )

    @staticmethod
    def _apply_to_node(
        workspace: CaseWorkspace, node: EvidenceNode, result: ProfileVerification
    ) -> None:
        node.attributes = {
            **node.attributes,
            "verification_status": result.status.value,
            "verification_score": result.score,
            "verification_reasons": result.reasons,
            "verification_negative_reasons": result.negative_reasons,
            "verified_profile": result.extracted,
            "last_verified_at": result.verified_at.isoformat(),
            "snapshot_path": result.snapshot_path,
            "changed_fields": result.changed_fields,
        }
        # Discovery tools are lead generators. Verification constrains rather than blindly boosts.
        if result.status in {VerificationStatus.VERIFIED, VerificationStatus.LIKELY}:
            node.confidence = max(node.confidence, result.score)
        elif result.status in {VerificationStatus.FALSE_POSITIVE, VerificationStatus.SOFT_404}:
            node.confidence = min(node.confidence, result.score)
            node.attributes["status"] = "negative"
        else:
            node.confidence = min(node.confidence, max(result.score, 0.2))
        node.confidence_label = (
            "High" if node.confidence >= 0.85 else "Medium" if node.confidence >= 0.65 else "Low"
        )
        events: list[TimelineEvent] = []
        for key in ("created_at", "updated_at", "last_seen"):
            raw = result.extracted.get(key)
            if not raw:
                continue
            try:
                occurred = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
                if occurred.tzinfo is None:
                    occurred = occurred.replace(tzinfo=UTC)
            except ValueError:
                continue
            event_id = (
                "event-"
                + hashlib.sha256(
                    f"{workspace.record.case_id}|{node.node_id}|verification|{key}|{occurred.isoformat()}".encode()
                ).hexdigest()[:20]
            )
            events.append(
                TimelineEvent(
                    event_id=event_id,
                    case_id=workspace.record.case_id,
                    title=f"{node.label}: verified {key.replace('_', ' ')}",
                    event_type=f"verified_{key}",
                    occurred_at=occurred,
                    node_id=node.node_id,
                    source=result.platform,
                    evidence_refs=[result.verification_id],
                    attributes={"value": raw, "verification_id": result.verification_id},
                )
            )
        workspace.save_graph([node], [], events)


class IdentityClusterEngine:
    """Build explainable identity clusters and contradiction-driven review tasks."""

    PROFILE_TYPES = ProfileVerifier.PROFILE_TYPES

    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def run(
        self, workspace: CaseWorkspace
    ) -> tuple[list[IdentityCluster], list[ReviewTask], list[EvidenceEdge]]:
        nodes = [
            node
            for node in workspace.nodes()
            if node.entity_type in self.PROFILE_TYPES
            or node.attributes.get("finding_kind") in {"profile", "web_profile", "email_account"}
        ][: self.config.identity.max_pairwise_profiles]
        pair_edges: list[EvidenceEdge] = []
        adjacency: dict[str, set[str]] = defaultdict(set)
        tasks: list[ReviewTask] = []
        for index, left in enumerate(nodes):
            for right in nodes[index + 1 :]:
                score, reasons, contradictions, factors = self._compare(left, right)
                if score >= self.config.identity.cluster_threshold:
                    relation = (
                        "likely_same_identity"
                        if score >= self.config.identity.strong_cluster_threshold
                        else "possibly_same_identity"
                    )
                    edge = EvidenceEdge(
                        edge_id=stable_edge_id(
                            workspace.record.case_id, left.node_id, right.node_id, relation
                        ),
                        case_id=workspace.record.case_id,
                        source_node_id=left.node_id,
                        target_node_id=right.node_id,
                        relation=relation,
                        label="likely same identity"
                        if relation.startswith("likely")
                        else "possibly same identity",
                        confidence=score,
                        confidence_label="High" if score >= 0.85 else "Medium",
                        reasons=reasons + [f"Contradiction: {item}" for item in contradictions],
                        factors=factors,
                        evidence_refs=sorted(set(left.evidence_refs + right.evidence_refs)),
                        attributes={"contradictions": contradictions, "identity_comparison": True},
                    )
                    pair_edges.append(edge)
                    adjacency[left.node_id].add(right.node_id)
                    adjacency[right.node_id].add(left.node_id)
                elif contradictions and score <= self.config.identity.contradiction_threshold:
                    relation = "likely_unrelated"
                    pair_edges.append(
                        EvidenceEdge(
                            edge_id=stable_edge_id(
                                workspace.record.case_id, left.node_id, right.node_id, relation
                            ),
                            case_id=workspace.record.case_id,
                            source_node_id=left.node_id,
                            target_node_id=right.node_id,
                            relation=relation,
                            label="likely unrelated",
                            confidence=min(0.95, 1.0 - score),
                            confidence_label="High" if score <= 0.15 else "Medium",
                            reasons=[f"Contradiction: {item}" for item in contradictions],
                            factors=factors,
                            attributes={
                                "contradictions": contradictions,
                                "identity_comparison": True,
                            },
                        )
                    )
        clusters = self._components(workspace, nodes, adjacency, pair_edges)
        clustered = {node_id for cluster in clusters for node_id in cluster.node_ids}
        for node in nodes:
            status = str(node.attributes.get("verification_status", "unverified"))
            if status in {
                VerificationStatus.FALSE_POSITIVE.value,
                VerificationStatus.SOFT_404.value,
            }:
                tasks.append(
                    self._task(
                        workspace,
                        node,
                        "Reject false-positive profile lead",
                        "high",
                        "Confirm that the candidate is a generic, missing, or soft-404 page and mark it rejected.",
                    )
                )
            elif node.node_id not in clustered:
                tasks.append(
                    self._task(
                        workspace,
                        node,
                        "Review isolated profile candidate",
                        "medium",
                        "Only weak or no cross-profile evidence connects this account. Compare avatar, biography, links, location, and activity manually.",
                    )
                )
            elif status in {"unverified", "error", "possible", "reachable"}:
                tasks.append(
                    self._task(
                        workspace,
                        node,
                        "Complete profile verification",
                        "medium",
                        "The account was discovered but not strongly verified. Open the preserved snapshot and validate the profile manually.",
                    )
                )
        for cluster in clusters:
            if cluster.contradictions:
                tasks.append(
                    ReviewTask(
                        task_id="review-"
                        + hashlib.sha256(
                            f"{workspace.record.case_id}|{cluster.cluster_id}|contradictions".encode()
                        ).hexdigest()[:20],
                        case_id=workspace.record.case_id,
                        title=f"Resolve contradictions in {cluster.label}",
                        description="; ".join(cluster.contradictions[:8]),
                        priority="high",
                        evidence_ids=cluster.node_ids,
                        recommended_action="Check conflicting names, locations, avatars, and linked websites before accepting the cluster.",
                    )
                )
        workspace.replace_identity_edges(pair_edges)
        workspace.replace_clusters(clusters)
        workspace.replace_review_tasks(tasks)
        return clusters, tasks, pair_edges

    def _compare(
        self, left: EvidenceNode, right: EvidenceNode
    ) -> tuple[float, list[str], list[str], list[ConfidenceFactor]]:
        left_features = self._features(left)
        right_features = self._features(right)
        score = 0.0
        reasons: list[str] = []
        contradictions: list[str] = []
        factors: list[ConfidenceFactor] = []

        def positive(key: str, weight: float, label: str) -> None:
            nonlocal score
            if (
                left_features.get(key)
                and right_features.get(key)
                and left_features[key] == right_features[key]
            ):
                score += weight
                reasons.append(label)
                factors.append(
                    ConfidenceFactor(
                        factor_id=f"match-{key}",
                        label=label,
                        effect=EvidenceEffect.POSITIVE,
                        weight=weight,
                        explanation=label,
                        evidence_refs=[left.node_id, right.node_id],
                    )
                )

        positive("website", 0.42, "Both profiles link to the same external website")
        positive("avatar_hash", 0.36, "Both profiles use the same exact avatar content hash")
        positive("display_name", 0.20, "Display names match after normalization")
        positive("location", 0.11, "Profile locations match")
        left_url = str(left_features.get("profile_url") or "")
        right_url = str(right_features.get("profile_url") or "")
        direct_link = bool(
            (right_url and right_url in set(left_features.get("external_profile_urls", [])))
            or (left_url and left_url in set(right_features.get("external_profile_urls", [])))
        )
        if direct_link:
            contribution = 0.78
            score += contribution
            reasons.append("One public profile explicitly links to the other profile")
            factors.append(
                ConfidenceFactor(
                    factor_id="direct-public-profile-link",
                    label="Direct public profile link",
                    effect=EvidenceEffect.POSITIVE,
                    weight=contribution,
                    explanation=(
                        "One public profile contains an explicit link to the other. This is strong "
                        "association evidence, but it is not standalone proof of identity."
                    ),
                    evidence_refs=[left.node_id, right.node_id],
                )
            )
        shared_domains = sorted(
            set(left_features.get("external_domains", []))
            & set(right_features.get("external_domains", []))
        )
        if shared_domains:
            contribution = min(0.3, 0.2 + 0.04 * len(shared_domains))
            score += contribution
            reasons.append(f"Profiles share external domain(s): {', '.join(shared_domains[:4])}")
            factors.append(
                ConfidenceFactor(
                    factor_id="shared-external-domains",
                    label="Shared external links",
                    effect=EvidenceEffect.POSITIVE,
                    weight=contribution,
                    explanation="Independent profile pages link to the same external domain.",
                    evidence_refs=[left.node_id, right.node_id],
                )
            )
        if left_features.get("avatar_dhash") and right_features.get("avatar_dhash"):
            distance = self._hamming_hex(
                str(left_features["avatar_dhash"]), str(right_features["avatar_dhash"])
            )
            if distance is not None and distance <= 6:
                contribution = 0.36 if distance <= 2 else 0.26
                score += contribution
                reasons.append(f"Avatars are visually similar (perceptual distance {distance}/64)")
                factors.append(
                    ConfidenceFactor(
                        factor_id="similar-avatar-dhash",
                        label="Visually similar avatars",
                        effect=EvidenceEffect.POSITIVE,
                        weight=contribution,
                        explanation=f"Perceptual avatar hashes differ by {distance} of 64 bits.",
                        evidence_refs=[left.node_id, right.node_id],
                    )
                )
        if (
            left_features.get("username")
            and right_features.get("username")
            and left_features["username"] == right_features["username"]
        ):
            username_weight = min(
                self.config.identity.username_only_cap,
                0.18 + min(0.14, len(str(left_features["username"])) / 100),
            )
            score += username_weight
            reasons.append("Usernames match exactly (weak evidence by itself)")
            factors.append(
                ConfidenceFactor(
                    factor_id="match-username",
                    label="Exact username",
                    effect=EvidenceEffect.POSITIVE,
                    weight=username_weight,
                    explanation="Exact usernames are useful leads but can be shared by unrelated people.",
                    evidence_refs=[left.node_id, right.node_id],
                )
            )
        elif left_features.get("username") and right_features.get("username"):
            left_compact = re.sub(r"[._-]+", "", str(left_features["username"]))
            right_compact = re.sub(r"[._-]+", "", str(right_features["username"]))
            if left_compact and left_compact == right_compact:
                contribution = 0.12
                score += contribution
                reasons.append("Usernames differ only by common separators (weak evidence)")
                factors.append(
                    ConfidenceFactor(
                        factor_id="similar-username-format",
                        label="Handle formatting variant",
                        effect=EvidenceEffect.POSITIVE,
                        weight=contribution,
                        explanation=(
                            "The handles become equal after removing periods, underscores, and "
                            "hyphens. This is only a discovery hint."
                        ),
                        evidence_refs=[left.node_id, right.node_id],
                    )
                )
        bio_score = self._jaccard(
            str(left_features.get("bio") or ""), str(right_features.get("bio") or "")
        )
        if bio_score >= 0.25:
            contribution = min(0.22, bio_score * 0.25)
            score += contribution
            reasons.append(f"Biography text overlaps ({bio_score:.0%} token similarity)")
            factors.append(
                ConfidenceFactor(
                    factor_id="similar-bio",
                    label="Biography similarity",
                    effect=EvidenceEffect.POSITIVE,
                    weight=contribution,
                    explanation=f"Normalized biography token similarity is {bio_score:.0%}.",
                    evidence_refs=[left.node_id, right.node_id],
                )
            )
        if (
            left_features.get("display_name")
            and right_features.get("display_name")
            and left_features["display_name"] != right_features["display_name"]
        ):
            name_similarity = self._jaccard(
                str(left_features["display_name"]), str(right_features["display_name"])
            )
            if name_similarity >= 0.5:
                contribution = 0.1
                score += contribution
                reasons.append("Display names are materially similar")
                factors.append(
                    ConfidenceFactor(
                        factor_id="similar-display-name",
                        label="Similar display names",
                        effect=EvidenceEffect.POSITIVE,
                        weight=contribution,
                        explanation=f"Normalized name-token similarity is {name_similarity:.0%}.",
                        evidence_refs=[left.node_id, right.node_id],
                    )
                )
            elif name_similarity < 0.2:
                score -= 0.18
                contradictions.append("Display names are materially different")
        if (
            left_features.get("location")
            and right_features.get("location")
            and left_features["location"] != right_features["location"]
            and self._jaccard(str(left_features["location"]), str(right_features["location"])) == 0
        ):
            score -= 0.06
            contradictions.append("Profile locations differ and require contextual review")
        if (
            left_features.get("avatar_hash")
            and right_features.get("avatar_hash")
            and left_features["avatar_hash"] != right_features["avatar_hash"]
        ):
            score -= 0.18
            contradictions.append("Exact avatar content hashes differ")
        if left_features.get("avatar_dhash") and right_features.get("avatar_dhash"):
            distance = self._hamming_hex(
                str(left_features["avatar_dhash"]), str(right_features["avatar_dhash"])
            )
            if distance is not None and distance >= 24:
                score -= 0.16
                contradictions.append(
                    f"Avatars are visually dissimilar (perceptual distance {distance}/64)"
                )
        if left_features.get("account_type") and right_features.get("account_type"):
            left_type = str(left_features["account_type"]).casefold()
            right_type = str(right_features["account_type"]).casefold()
            if {left_type, right_type} & {"organization", "company"} and left_type != right_type:
                score -= 0.12
                contradictions.append(
                    "One profile appears organizational while the other appears personal"
                )
        score = max(0.0, min(0.99, score))
        for item in contradictions:
            factors.append(
                ConfidenceFactor(
                    factor_id="contradiction-" + hashlib.sha1(item.encode()).hexdigest()[:8],
                    label=item,
                    effect=EvidenceEffect.NEGATIVE,
                    weight=-0.15,
                    explanation=item,
                    evidence_refs=[left.node_id, right.node_id],
                )
            )
        return score, reasons, contradictions, factors

    @staticmethod
    def _features(node: EvidenceNode) -> dict[str, Any]:
        verified = node.attributes.get("verified_profile") or {}
        url = str(node.attributes.get("url") or node.value)
        parsed = urllib.parse.urlsplit(url)
        path_parts = [part for part in parsed.path.split("/") if part]
        username = (
            str(
                verified.get("username")
                or node.attributes.get("username")
                or (path_parts[-1] if path_parts else "")
            )
            .lstrip("@")
            .casefold()
        )
        website = IdentityClusterEngine._canonical_web_identity(str(verified.get("website") or ""))
        display = re.sub(r"\W+", " ", str(verified.get("display_name") or "").casefold()).strip()
        location = re.sub(r"\W+", " ", str(verified.get("location") or "").casefold()).strip()
        bio = str(verified.get("bio") or verified.get("description") or "").casefold()
        avatar_hash = str(verified.get("avatar_hash") or node.attributes.get("avatar_hash") or "")
        avatar_dhash = str(verified.get("avatar_dhash") or "")
        # Only author-declared identity links may contribute to identity
        # clustering. Generic outbound anchors often contain site chrome,
        # support pages, advertisements, or arbitrary content links.
        links = verified.get("identity_links") or []
        external_domains = []
        external_profile_urls = []
        for link in links if isinstance(links, list) else []:
            canonical_link = IdentityClusterEngine._canonical_web_identity(str(link))
            host = (urllib.parse.urlsplit(canonical_link).hostname or "").casefold()
            if host.startswith("www."):
                host = host[4:]
            if host and host not in external_domains:
                external_domains.append(host)
            if canonical_link and canonical_link not in external_profile_urls:
                external_profile_urls.append(canonical_link)
        if website:
            host = (urllib.parse.urlsplit(website).hostname or "").casefold()
            if host.startswith("www."):
                host = host[4:]
            if host and host not in external_domains:
                external_domains.append(host)
        return {
            "username": username,
            "profile_url": IdentityClusterEngine._canonical_web_identity(url),
            "website": website,
            "display_name": display,
            "location": location,
            "bio": bio,
            "avatar_hash": avatar_hash,
            "avatar_dhash": avatar_dhash,
            "external_domains": external_domains,
            "external_profile_urls": external_profile_urls,
            "account_type": verified.get("account_type") or verified.get("type") or "",
        }

    @staticmethod
    def _canonical_web_identity(value: str) -> str:
        candidate = value.strip()
        if not candidate:
            return ""
        if not candidate.startswith(("http://", "https://")):
            candidate = f"https://{candidate}"
        parsed = urllib.parse.urlsplit(candidate)
        host = (parsed.hostname or "").casefold()
        if host.startswith("www."):
            host = host[4:]
        path = parsed.path.rstrip("/")
        return urllib.parse.urlunsplit(("https", host, path, "", "")) if host else ""

    @staticmethod
    def _hamming_hex(left: str, right: str) -> int | None:
        try:
            if len(left) != len(right) or not left:
                return None
            return (int(left, 16) ^ int(right, 16)).bit_count()
        except ValueError:
            return None

    @staticmethod
    def _jaccard(left: str, right: str) -> float:
        stop = {"the", "and", "or", "a", "an", "i", "me", "my", "of", "in", "on", "to"}
        a = {token for token in re.findall(r"[\w-]{2,}", left.casefold()) if token not in stop}
        b = {token for token in re.findall(r"[\w-]{2,}", right.casefold()) if token not in stop}
        return len(a & b) / len(a | b) if a and b else 0.0

    def _components(
        self,
        workspace: CaseWorkspace,
        nodes: list[EvidenceNode],
        adjacency: dict[str, set[str]],
        edges: list[EvidenceEdge],
    ) -> list[IdentityCluster]:
        by_id = {node.node_id: node for node in nodes}
        seen: set[str] = set()
        clusters: list[IdentityCluster] = []
        for start in sorted(adjacency):
            if start in seen:
                continue
            stack = [start]
            members: list[str] = []
            while stack:
                current = stack.pop()
                if current in seen:
                    continue
                seen.add(current)
                members.append(current)
                stack.extend(adjacency[current] - seen)
            if len(members) < 2:
                continue
            member_edges = [
                edge
                for edge in edges
                if edge.source_node_id in members
                and edge.target_node_id in members
                and edge.relation != "likely_unrelated"
            ]
            negative_edges = [
                edge
                for edge in edges
                if edge.source_node_id in members
                and edge.target_node_id in members
                and edge.relation == "likely_unrelated"
            ]
            confidence = sum(edge.confidence for edge in member_edges) / max(1, len(member_edges))
            if negative_edges:
                penalty = min(0.35, max(edge.confidence for edge in negative_edges) * 0.3)
                confidence = max(0.0, confidence - penalty)
            contradictions = sorted(
                {
                    item
                    for edge in [*member_edges, *negative_edges]
                    for item in [
                        *edge.attributes.get("contradictions", []),
                        *[
                            reason.removeprefix("Contradiction: ")
                            for reason in edge.reasons
                            if reason.startswith("Contradiction:")
                        ],
                    ]
                }
            )
            label_nodes = [by_id[item].label for item in members if item in by_id]
            cluster_id = (
                "cluster-"
                + hashlib.sha256(
                    f"{workspace.record.case_id}|{'|'.join(sorted(members))}".encode()
                ).hexdigest()[:20]
            )
            clusters.append(
                IdentityCluster(
                    cluster_id=cluster_id,
                    case_id=workspace.record.case_id,
                    label=f"Identity cluster: {', '.join(label_nodes[:3])}",
                    node_ids=sorted(members),
                    confidence=confidence,
                    confidence_label="High"
                    if confidence >= 0.85
                    else "Medium"
                    if confidence >= 0.65
                    else "Low",
                    reasons=sorted(
                        {
                            reason
                            for edge in member_edges
                            for reason in edge.reasons
                            if not reason.startswith("Contradiction:")
                        }
                    ),
                    contradictions=contradictions,
                )
            )
        return clusters

    @staticmethod
    def _task(
        workspace: CaseWorkspace, node: EvidenceNode, title: str, priority: str, action: str
    ) -> ReviewTask:
        return ReviewTask(
            task_id="review-"
            + hashlib.sha256(
                f"{workspace.record.case_id}|{node.node_id}|{title}".encode()
            ).hexdigest()[:20],
            case_id=workspace.record.case_id,
            title=title,
            description=f"Candidate: {node.label} ({node.value})",
            priority=priority,
            evidence_ids=[node.node_id],
            recommended_action=action,
        )
