from __future__ import annotations

import json
from pathlib import Path

from mia.models import PluginContext, ProcessResult, ScanProfile, TargetType
from mia.plugins.exiftool import ExifToolPlugin
from mia.plugins.holehe import HolehePlugin
from mia.plugins.maigret import MaigretPlugin
from mia.plugins.sherlock import SherlockPlugin
from mia.plugins.spiderfoot import SpiderFootPlugin
from mia.plugins.whois import WhoisPlugin


def context_for(tmp_path: Path, target: str, target_type: TargetType, plugin: str) -> PluginContext:
    raw = tmp_path / "raw" / plugin
    raw.mkdir(parents=True)
    return PluginContext(
        scan_id="scan",
        target=target,
        target_type=target_type,
        profile=ScanProfile.DEEP,
        scan_dir=tmp_path,
        raw_dir=raw,
        timeout_seconds=30,
    )


def process_with(process_result: ProcessResult, stdout: str, raw_dir: Path) -> ProcessResult:
    path = raw_dir / "stdout.txt"
    path.write_text(stdout, encoding="utf-8")
    return process_result.model_copy(update={"stdout": stdout, "stdout_path": str(path)})


def test_maigret_parser(tmp_path: Path, process_result: ProcessResult) -> None:
    context = context_for(tmp_path, "octocat", TargetType.USERNAME, "maigret")
    payload = {
        "query_username": "octocat",
        "matches": [
            {
                "site": "GitHub",
                "url_user": "https://github.com/octocat",
                "status": "FOUND",
                "score": 0.99,
                "ids": {"name": "The Octocat"},
            }
        ],
    }
    (context.raw_dir / "report_octocat_simple.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )
    findings = MaigretPlugin().parse(context, process_with(process_result, "", context.raw_dir))
    assert len(findings) == 1
    assert findings[0].title == "GitHub"
    assert findings[0].url == "https://github.com/octocat"


def test_maigret_parser_cleans_serialized_site_metadata(
    tmp_path: Path, process_result: ProcessResult
) -> None:
    context = context_for(tmp_path, "bobobebra", TargetType.USERNAME, "maigret")
    site_metadata = str(
        {
            "tags": ["coding"],
            "urlMain": "https://www.github.com/",
            "url": "https://github.com/{username}",
            "checkType": "status_code",
        }
    )
    payload = {
        site_metadata: {
            "url_user": "https://github.com/bobobebra",
            "status": "FOUND",
            "username": "bobobebra",
        }
    }
    (context.raw_dir / "report_bobobebra_simple.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )

    findings = MaigretPlugin().parse(context, process_with(process_result, "", context.raw_dir))

    assert len(findings) == 1
    assert findings[0].title == "GitHub"
    assert "{'tags'" not in findings[0].title


def test_sherlock_parser(tmp_path: Path, process_result: ProcessResult) -> None:
    context = context_for(tmp_path, "octocat", TargetType.USERNAME, "sherlock")
    stdout = "[+] GitHub: https://github.com/octocat\n[+] Reddit: https://reddit.com/user/octocat\n"
    findings = SherlockPlugin().parse(
        context, process_with(process_result, stdout, context.raw_dir)
    )
    assert {item.title for item in findings} == {"GitHub", "Reddit"}


def test_spiderfoot_parser(tmp_path: Path, process_result: ProcessResult) -> None:
    context = context_for(tmp_path, "example.com", TargetType.DOMAIN, "spiderfoot")
    stdout = json.dumps(
        [
            {"type": "INTERNET_NAME", "data": "www.example.com", "module": "sfp_dnsresolve"},
            {
                "type": "LINKED_URL_INTERNAL",
                "data": "https://example.com/about",
                "module": "sfp_spider",
            },
        ]
    )
    findings = SpiderFootPlugin().parse(
        context, process_with(process_result, stdout, context.raw_dir)
    )
    assert len(findings) == 2
    assert {item.kind for item in findings} == {"domain", "url"}


def test_holehe_parser(tmp_path: Path, process_result: ProcessResult) -> None:
    context = context_for(tmp_path, "person@example.com", TargetType.EMAIL, "holehe")
    stdout = json.dumps(
        [
            {"domain": "github.com", "exists": True, "rateLimit": False, "emailrecovery": None},
            {"domain": "example.net", "exists": False, "rateLimit": False},
        ]
    )
    findings = HolehePlugin().parse(context, process_with(process_result, stdout, context.raw_dir))
    assert len(findings) == 1
    assert findings[0].value == "github.com"


def test_exiftool_parser(tmp_path: Path, process_result: ProcessResult) -> None:
    context = context_for(tmp_path, "/tmp/photo.jpg", TargetType.FILE, "exiftool")
    stdout = json.dumps([{"[File]FileName": "photo.jpg", "[EXIF]GPSLatitude": 62.3}])
    findings = ExifToolPlugin().parse(
        context, process_with(process_result, stdout, context.raw_dir)
    )
    assert len(findings) == 2
    assert any(item.category == "Geolocation" for item in findings)


def test_whois_parser(tmp_path: Path, process_result: ProcessResult) -> None:
    context = context_for(tmp_path, "example.com", TargetType.DOMAIN, "whois")
    stdout = (
        "Domain Name: EXAMPLE.COM\nRegistrar: Example Registrar\nName Server: NS1.EXAMPLE.COM\n"
    )
    findings = WhoisPlugin().parse(context, process_with(process_result, stdout, context.raw_dir))
    assert len(findings) == 3


def test_subfinder_parser_accepts_json_lines(tmp_path: Path, process_result: ProcessResult) -> None:
    from mia.plugins.extended import SubfinderPlugin

    context = context_for(tmp_path, "example.com", TargetType.DOMAIN, "subfinder")
    stdout = "\n".join(
        [
            json.dumps({"host": "api.example.com", "source": "crtsh"}),
            json.dumps({"host": "outside.test", "source": "other"}),
            "www.example.com",
        ]
    )
    findings = SubfinderPlugin().parse(
        context, process_with(process_result, stdout, context.raw_dir)
    )
    assert {item.value for item in findings} == {"api.example.com", "www.example.com"}


def test_assetfinder_parser_deduplicates_domains(
    tmp_path: Path, process_result: ProcessResult
) -> None:
    from mia.plugins.extended import AssetfinderPlugin

    context = context_for(tmp_path, "example.com", TargetType.DOMAIN, "assetfinder")
    stdout = "a.example.com\na.example.com\nnot-example.net\n"
    findings = AssetfinderPlugin().parse(
        context, process_with(process_result, stdout, context.raw_dir)
    )
    assert [item.value for item in findings] == ["a.example.com"]


def test_gau_parser_keeps_structured_attributes(
    tmp_path: Path, process_result: ProcessResult
) -> None:
    from mia.plugins.extended import GauPlugin

    context = context_for(tmp_path, "example.com", TargetType.DOMAIN, "gau")
    stdout = json.dumps({"url": "https://example.com/old", "status": "200"})
    findings = GauPlugin().parse(context, process_with(process_result, stdout, context.raw_dir))
    assert findings[0].url == "https://example.com/old"
    assert findings[0].attributes["status"] == "200"


def test_httpx_parser_ignores_malformed_lines(
    tmp_path: Path, process_result: ProcessResult
) -> None:
    from mia.plugins.extended import HttpxPlugin

    context = context_for(tmp_path, "example.com", TargetType.DOMAIN, "httpx")
    stdout = "broken\n" + json.dumps(
        {
            "url": "https://example.com",
            "title": "Example",
            "status_code": 200,
            "tech": ["nginx"],
        }
    )
    findings = HttpxPlugin().parse(context, process_with(process_result, stdout, context.raw_dir))
    assert len(findings) == 1
    assert findings[0].title == "Example"
    assert findings[0].attributes["status_code"] == 200


def test_dnstwist_parser_excludes_original_domain(
    tmp_path: Path, process_result: ProcessResult
) -> None:
    from mia.plugins.extended import DnstwistPlugin

    context = context_for(tmp_path, "example.com", TargetType.DOMAIN, "dnstwist")
    stdout = json.dumps(
        [
            {"domain-name": "example.com", "fuzzer": "original"},
            {"domain-name": "examp1e.com", "fuzzer": "homoglyph"},
        ]
    )
    findings = DnstwistPlugin().parse(
        context, process_with(process_result, stdout, context.raw_dir)
    )
    assert [item.value for item in findings] == ["examp1e.com"]


def test_theharvester_parser_extracts_conservative_records(
    tmp_path: Path, process_result: ProcessResult
) -> None:
    from mia.plugins.extended import TheHarvesterPlugin

    context = context_for(tmp_path, "example.com", TargetType.DOMAIN, "theharvester")
    stdout = "admin@example.com\napi.example.com\nhttps://example.com/about\noutsider@other.test\n"
    findings = TheHarvesterPlugin().parse(
        context, process_with(process_result, stdout, context.raw_dir)
    )
    assert any(item.value == "admin@example.com" for item in findings)
    assert any(item.value == "api.example.com" for item in findings)
    assert any(item.value == "https://example.com/about" for item in findings)


def test_phoneinfoga_parser_preserves_summary_and_urls(
    tmp_path: Path, process_result: ProcessResult
) -> None:
    from mia.plugins.extended import PhoneInfogaPlugin

    context = context_for(tmp_path, "+461234567", TargetType.PHONE, "phoneinfoga")
    stdout = "Country: Sweden\nSearch: https://example.test/lookup?q=461234567\n"
    findings = PhoneInfogaPlugin().parse(
        context, process_with(process_result, stdout, context.raw_dir)
    )
    assert any(item.kind == "phone_summary" for item in findings)
    assert any(item.url == "https://example.test/lookup?q=461234567" for item in findings)
