from __future__ import annotations

import json

import pytest
from click import unstyle
from typer.testing import CliRunner

from mia.assistant import InvestigationAssistant
from mia.cli import app
from mia.config import AppConfig
from mia.http import AsyncJsonClient, JsonResponse
from mia.models import EvidenceEdge, EvidenceNode
from mia.secrets import SecretStore

runner = CliRunner()


def evidence() -> tuple[list[EvidenceNode], list[EvidenceEdge]]:
    nodes = [
        EvidenceNode(
            node_id="node-root",
            case_id="case-1",
            entity_type="username",
            label="alice",
            value="alice",
            canonical_value="alice",
            confidence=1.0,
            confidence_label="High",
            sources=["manual"],
            attributes={"root_target": True},
        ),
        EvidenceNode(
            node_id="node-email",
            case_id="case-1",
            entity_type="email",
            label="alice@example.com",
            value="alice@example.com",
            canonical_value="alice@example.com",
            confidence=0.9,
            confidence_label="High",
            sources=["fixture"],
        ),
    ]
    edges = [
        EvidenceEdge(
            edge_id="edge-email",
            case_id="case-1",
            source_node_id="node-root",
            target_node_id="node-email",
            relation="associated_email",
            label="Associated email",
            confidence=0.9,
            confidence_label="High",
            reasons=["Fixture evidence"],
        )
    ]
    return nodes, edges


def grounded_payload() -> dict[str, object]:
    return {
        "executive_summary": [
            {
                "text": "The username is connected to one email finding.",
                "evidence_ids": ["node-root", "edge-email"],
                "confidence": "high",
            }
        ],
        "notable_findings": [
            {
                "text": "An email was reported by the fixture source.",
                "evidence_ids": ["node-email"],
                "confidence": "high",
            }
        ],
        "uncertainty_warnings": [],
        "suggested_next_steps": [
            {
                "text": "Manually verify the email relationship.",
                "evidence_ids": ["node-email"],
                "confidence": "medium",
            }
        ],
    }


@pytest.mark.asyncio
async def test_gemini_provider_uses_generate_content_and_validates_citations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = AppConfig()
    config.assistant.providers["gemini"].model = "gemini-test"
    monkeypatch.setenv("GEMINI_API_KEY", "secret")
    captured: dict[str, object] = {}

    async def fake_request(self, method, url, **kwargs):  # type: ignore[no-untyped-def]
        captured.update({"method": method, "url": url, **kwargs})
        return JsonResponse(
            200,
            {"candidates": [{"content": {"parts": [{"text": json.dumps(grounded_payload())}]}}]},
            {},
        )

    monkeypatch.setattr(AsyncJsonClient, "request", fake_request)
    nodes, edges = evidence()
    summary = await InvestigationAssistant(config).summarize(nodes, edges, provider="gemini")

    assert summary.provider == "gemini"
    assert summary.rejected_ungrounded_statements == 0
    assert captured["method"] == "POST"
    assert str(captured["url"]).endswith("/models/gemini-test:generateContent")
    assert captured["headers"]["x-goog-api-key"] == "secret"  # type: ignore[index]
    body = captured["json_body"]  # type: ignore[assignment]
    assert body["generationConfig"]["responseMimeType"] == "application/json"  # type: ignore[index]
    assert "responseJsonSchema" in body["generationConfig"]  # type: ignore[index]


@pytest.mark.asyncio
async def test_ollama_provider_is_keyless_local_and_uses_structured_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = AppConfig()
    config.assistant.providers["ollama"].model = "qwen-test:latest"
    captured: dict[str, object] = {}

    async def fake_request(self, method, url, **kwargs):  # type: ignore[no-untyped-def]
        captured.update({"method": method, "url": url, **kwargs})
        return JsonResponse(
            200,
            {"message": {"role": "assistant", "content": json.dumps(grounded_payload())}},
            {},
        )

    monkeypatch.setattr(AsyncJsonClient, "request", fake_request)
    nodes, edges = evidence()
    summary = await InvestigationAssistant(config).summarize(nodes, edges, provider="ollama")

    assert summary.provider == "ollama"
    assert captured["url"] == "http://localhost:11434/api/chat"
    assert "Authorization" not in captured["headers"]  # type: ignore[operator]
    body = captured["json_body"]  # type: ignore[assignment]
    assert body["stream"] is False  # type: ignore[index]
    assert body["think"] is False  # type: ignore[index]
    assert isinstance(body["format"], dict)  # type: ignore[index]


@pytest.mark.asyncio
async def test_ollama_cloud_uses_optional_key_and_prompt_json_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = AppConfig()
    settings = config.assistant.providers["ollama"]
    settings.model = "cloud-model"
    settings.endpoint = "https://ollama.com/api"
    monkeypatch.setenv("OLLAMA_API_KEY", "cloud-secret")
    captured: dict[str, object] = {}

    async def fake_request(self, method, url, **kwargs):  # type: ignore[no-untyped-def]
        captured.update({"method": method, "url": url, **kwargs})
        return JsonResponse(
            200,
            {"message": {"role": "assistant", "content": json.dumps(grounded_payload())}},
            {},
        )

    monkeypatch.setattr(AsyncJsonClient, "request", fake_request)
    nodes, edges = evidence()
    await InvestigationAssistant(config).summarize(nodes, edges, provider="ollama")

    assert captured["headers"]["Authorization"] == "Bearer cloud-secret"  # type: ignore[index]
    assert "format" not in captured["json_body"]  # type: ignore[operator]


@pytest.mark.asyncio
async def test_remote_provider_discards_unknown_evidence_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = AppConfig()
    config.assistant.providers["gemini"].model = "gemini-test"
    monkeypatch.setenv("GEMINI_API_KEY", "secret")
    payload = grounded_payload()
    payload["notable_findings"] = [
        {
            "text": "Unsupported statement.",
            "evidence_ids": ["node-invented"],
            "confidence": "high",
        }
    ]

    async def fake_request(self, method, url, **kwargs):  # type: ignore[no-untyped-def]
        return JsonResponse(
            200,
            {"candidates": [{"content": {"parts": [{"text": json.dumps(payload)}]}}]},
            {},
        )

    monkeypatch.setattr(AsyncJsonClient, "request", fake_request)
    nodes, edges = evidence()
    summary = await InvestigationAssistant(config).summarize(nodes, edges, provider="gemini")

    assert summary.notable_findings == []
    assert summary.rejected_ungrounded_statements == 1


def test_secret_store_accepts_gemini_environment_aliases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = AppConfig()
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("GOOGLE_API_KEY", "alias-secret")
    store = SecretStore(config)
    assert store.get("gemini") == "alias-secret"
    assert store.source("gemini") == "environment (GOOGLE_API_KEY)"


def test_assistant_provider_cli_and_configuration(tmp_path, monkeypatch) -> None:
    config_path = tmp_path / "config.yaml"
    monkeypatch.setenv("MIA_CONFIG", str(config_path))
    monkeypatch.setenv("MIA_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("MIA_CASES_DIR", str(tmp_path / "cases"))

    configured = runner.invoke(
        app,
        [
            "assistant",
            "configure",
            "gemini",
            "--model",
            "gemini-test",
            "--default",
        ],
    )
    assert configured.exit_code == 0, configured.stdout
    contents = config_path.read_text(encoding="utf-8")
    assert "provider: gemini" in contents
    assert "model: gemini-test" in contents

    listed = runner.invoke(app, ["assistant", "providers", "--json"])
    assert listed.exit_code == 0, listed.stdout
    assert '"provider": "gemini"' in listed.stdout
    assert '"model": "gemini-test"' in listed.stdout


def test_case_summarize_help_lists_gemini_and_ollama() -> None:
    result = runner.invoke(app, ["case", "summarize", "--help"], env={"COLUMNS": "160"})
    assert result.exit_code == 0, result.stdout
    assert "gemini" in result.stdout
    assert "ollama" in result.stdout
    assert "--model" in unstyle(result.stdout)


def test_legacy_openai_fields_seed_provider_settings() -> None:
    config = AppConfig.model_validate(
        {
            "assistant": {
                "provider": "openai-compatible",
                "endpoint": "https://legacy.example/v1/chat/completions",
                "model": "legacy-model",
                "api_service": "assistant",
                "timeout": 123,
                "providers": {
                    "openai-compatible": {
                        "endpoint": "https://api.openai.com/v1/chat/completions",
                        "model": "",
                        "api_service": "assistant",
                        "timeout": 90,
                        "requires_key": True,
                    }
                },
            }
        }
    )
    settings = config.assistant.settings("openai-compatible")
    assert settings.endpoint == "https://legacy.example/v1/chat/completions"
    assert settings.model == "legacy-model"
    assert settings.timeout == 123


@pytest.mark.asyncio
async def test_configured_default_provider_is_used_when_provider_is_omitted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = AppConfig()
    config.assistant.provider = "ollama"
    config.assistant.providers["ollama"].model = "fixture-model"

    async def fake_request(self, method, url, **kwargs):  # type: ignore[no-untyped-def]
        return JsonResponse(
            200,
            {"message": {"role": "assistant", "content": json.dumps(grounded_payload())}},
            {},
        )

    monkeypatch.setattr(AsyncJsonClient, "request", fake_request)
    nodes, edges = evidence()
    summary = await InvestigationAssistant(config).summarize(nodes, edges)
    assert summary.provider == "ollama"


@pytest.mark.asyncio
async def test_ollama_cloud_requires_a_key() -> None:
    config = AppConfig()
    settings = config.assistant.providers["ollama"]
    settings.model = "cloud-model"
    settings.endpoint = "https://ollama.com/api"
    nodes, edges = evidence()
    with pytest.raises(RuntimeError, match="Ollama Cloud requires a credential"):
        await InvestigationAssistant(config).summarize(nodes, edges, provider="ollama")
