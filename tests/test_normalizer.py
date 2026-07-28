from mia.config import ConfidenceConfig
from mia.models import Finding
from mia.normalizer import canonicalize_url, merge_findings


def test_canonicalize_url_removes_tracking() -> None:
    assert (
        canonicalize_url("HTTPS://www.GitHub.com/octocat/?utm_source=x#bio")
        == "https://github.com/octocat"
    )


def test_merge_corrobated_profiles() -> None:
    findings = [
        Finding(
            plugin_id="maigret",
            category="Profiles",
            kind="profile",
            title="GitHub",
            value="https://github.com/octocat/",
            url="https://github.com/octocat/",
            source_confidence=0.82,
        ),
        Finding(
            plugin_id="sherlock",
            category="Profiles",
            kind="profile",
            title="github.com",
            value="https://www.github.com/octocat?utm_source=test",
            url="https://www.github.com/octocat?utm_source=test",
            source_confidence=0.78,
        ),
    ]
    confidence = ConfidenceConfig(default_source_reliability={"maigret": 0.72, "sherlock": 0.68})
    merged = merge_findings(findings, confidence)
    assert len(merged) == 1
    assert merged[0].sources == ["maigret", "sherlock"]
    assert merged[0].occurrences == 2
    assert merged[0].confidence_label == "High"
