from __future__ import annotations

from pathlib import Path

from mia.account_discovery import (
    LinkedAccountImporter,
    expand_account_seeds,
    parse_public_profile_url,
    username_variants,
)
from mia.config import AppConfig
from mia.graph import canonical_entity, stable_edge_id, stable_node_id
from mia.models import DeepCaseSeed, EvidenceEdge, EvidenceNode, ScanProfile, TargetType
from mia.verification import IdentityClusterEngine, ProfileVerifier, _ProfileHTMLParser
from mia.workspace import CaseManager


def test_parse_common_public_profile_urls() -> None:
    tiktok = parse_public_profile_url("https://www.tiktok.com/@Example.User?lang=en")
    instagram = parse_public_profile_url("https://instagram.com/example_user/")
    youtube = parse_public_profile_url("https://youtube.com/@ExampleChannel/videos")

    assert tiktok and (tiktok.platform, tiktok.username) == ("tiktok", "Example.User")
    assert instagram and (instagram.platform, instagram.username) == (
        "instagram",
        "example_user",
    )
    assert youtube and (youtube.platform, youtube.username) == (
        "youtube",
        "ExampleChannel",
    )
    assert parse_public_profile_url("https://instagram.com/explore/") is None
    assert parse_public_profile_url("https://example.com/@someone") is None
    assert parse_public_profile_url("https://support.x.com/articles/20170514") is None
    assert parse_public_profile_url("https://business.x.com/en/help/example") is None
    roblox = parse_public_profile_url("https://roblox.com/user.aspx?username=ExampleUser")
    assert roblox and roblox.username == "ExampleUser"
    assert roblox.url.endswith("?username=ExampleUser")


def test_only_author_declared_identity_links_are_promoted() -> None:
    parser = _ProfileHTMLParser()
    parser.feed(
        """
        <html><head>
          <link rel="me" href="https://instagram.com/example_user">
          <script type="application/ld+json">
            {"@type":"Person","url":"https://example.com/example_user","sameAs":["https://x.com/example_user"]}
          </script>
        </head><body>
          <a href="https://facebook.com/Sketchfab">ordinary content link</a>
          <a href="https://support.x.com/articles/20170514">support</a>
        </body></html>
        """
    )

    links = ProfileVerifier._identity_links(
        "https://example.com/profile", parser, username="example_user"
    )

    assert links == [
        "https://instagram.com/example_user",
        "https://x.com/example_user",
    ]


def test_username_variants_are_bounded_and_explainable() -> None:
    variants = username_variants("example.user_24", limit=6)

    assert variants[0].username == "example.user_24"
    assert variants[0].confidence == 1.0
    assert len(variants) <= 6
    assert len({item.username.casefold() for item in variants}) == len(variants)
    assert all(item.reason for item in variants)


def test_account_workflow_extracts_handle_from_profile_url() -> None:
    seeds, generated = expand_account_seeds(
        [
            DeepCaseSeed(
                target="https://www.tiktok.com/@example.user",
                target_type=TargetType.URL,
            )
        ],
        ScanProfile.DEFAULT,
    )

    handles = [seed for seed in seeds if seed.target_type == TargetType.USERNAME]
    assert generated >= 1
    assert handles[0].target == "example.user"
    assert "tiktok" in handles[0].tags
    assert any(seed.target == "exampleuser" for seed in handles)


def test_import_explicit_public_profile_link_and_score_relationship(tmp_path: Path) -> None:
    manager = CaseManager(tmp_path / "cases")
    workspace = manager.create("Linked profiles")
    source_url = "https://www.tiktok.com/@example.user"
    source = EvidenceNode(
        node_id=stable_node_id(
            workspace.record.case_id, "account", canonical_entity("account", source_url)
        ),
        case_id=workspace.record.case_id,
        entity_type="account",
        label="TikTok: @example.user",
        value=source_url,
        canonical_value=canonical_entity("account", source_url),
        confidence=0.9,
        confidence_label="High",
        sources=["test"],
        attributes={
            "url": source_url,
            "finding_kind": "profile",
            "verification_status": "likely",
            "verified_profile": {
                "username": "example.user",
                "external_links": ["https://facebook.com/Sketchfab"],
                "identity_links": ["https://instagram.com/example_user/"],
            },
        },
    )
    workspace.save_graph([source], [], [])

    linked = LinkedAccountImporter().import_from_verifications(workspace)
    assert len(linked) == 1
    assert linked[0].attributes["platform"] == "instagram"
    assert linked[0].attributes["username"] == "example_user"
    assert any(edge.relation == "links_to_account" for edge in workspace.edges())

    score, reasons, contradictions, factors = IdentityClusterEngine(AppConfig())._compare(
        source, linked[0]
    )
    assert score >= 0.78
    assert any("explicitly links" in reason for reason in reasons)
    assert not contradictions
    assert any(factor.factor_id == "direct-public-profile-link" for factor in factors)


def test_importer_removes_legacy_links_from_arbitrary_page_anchors(tmp_path: Path) -> None:
    workspace = CaseManager(tmp_path / "cases").create("Legacy false links")
    source_url = "https://gist.github.com/bobobebra"
    false_url = "https://instagram.com/sketchfab"
    source = EvidenceNode(
        node_id=stable_node_id(
            workspace.record.case_id, "account", canonical_entity("account", source_url)
        ),
        case_id=workspace.record.case_id,
        entity_type="account",
        label="Gist: @bobobebra",
        value=source_url,
        canonical_value=canonical_entity("account", source_url),
        confidence=0.96,
        confidence_label="High",
        sources=["maigret"],
        attributes={
            "url": source_url,
            "finding_kind": "profile",
            "verification_status": "verified",
            "verified_profile": {
                "username": "bobobebra",
                "external_links": [
                    false_url,
                    "https://support.x.com/articles/20170514",
                ],
                "identity_links": [],
            },
        },
    )
    false_node = EvidenceNode(
        node_id=stable_node_id(
            workspace.record.case_id, "account", canonical_entity("account", false_url)
        ),
        case_id=workspace.record.case_id,
        entity_type="account",
        label="Instagram: @sketchfab",
        value=false_url,
        canonical_value=canonical_entity("account", false_url),
        confidence=0.9,
        confidence_label="High",
        sources=["public-profile-link"],
        attributes={
            "finding_kind": "profile",
            "url": false_url,
            "platform": "instagram",
            "username": "sketchfab",
            "discovery_method": "explicit_public_profile_link",
        },
    )
    false_edge = EvidenceEdge(
        edge_id=stable_edge_id(
            workspace.record.case_id,
            source.node_id,
            false_node.node_id,
            "links_to_account",
        ),
        case_id=workspace.record.case_id,
        source_node_id=source.node_id,
        target_node_id=false_node.node_id,
        relation="links_to_account",
        label="publicly links to account",
        confidence=0.9,
        confidence_label="High",
    )
    workspace.save_graph([source, false_node], [false_edge], [])

    linked = LinkedAccountImporter().import_from_verifications(workspace)

    assert linked == []
    assert all(node.value != false_url for node in workspace.nodes())
    assert all(edge.relation != "links_to_account" for edge in workspace.edges())
