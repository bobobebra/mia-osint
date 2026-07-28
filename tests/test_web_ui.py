from __future__ import annotations

import time
from pathlib import Path

import yaml
from click import unstyle
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from mia.cli import app as cli_app
from mia.web import create_app


def _config(tmp_path: Path) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "paths": {
                    "output_dir": str(tmp_path / "reports"),
                    "cases_dir": str(tmp_path / "cases"),
                    "state_dir": str(tmp_path / "state"),
                    "log_dir": str(tmp_path / "logs"),
                    "user_plugins_dir": str(tmp_path / "plugins"),
                },
                "execution": {"cache": {"enabled": False}},
            }
        ),
        encoding="utf-8",
    )
    return path


def _wait(client: TestClient, operation_id: str) -> dict:
    for _ in range(200):
        payload = client.get(f"/api/operations/{operation_id}").json()
        if payload["status"] in {"completed", "failed", "cancelled"}:
            return payload
        time.sleep(0.02)
    raise AssertionError("operation did not finish")


def test_each_interface_has_one_public_launch_command() -> None:
    runner = CliRunner()
    workbench = runner.invoke(cli_app, ["workbench", "--help"], env={"COLUMNS": "160"})
    discover = runner.invoke(cli_app, ["discover", "--help"], env={"COLUMNS": "160"})
    removed_alias = runner.invoke(cli_app, ["ui", "--help"], env={"COLUMNS": "160"})
    removed_nested = runner.invoke(cli_app, ["workbench", "ui", "--help"], env={"COLUMNS": "160"})
    assert workbench.exit_code == 0
    assert discover.exit_code == 0
    assert "MIA Workbench" in workbench.stdout
    assert "MIA Discover" in discover.stdout
    assert "--no-browser" in unstyle(workbench.stdout)
    assert "--no-browser" in unstyle(discover.stdout)
    assert removed_alias.exit_code != 0
    assert removed_nested.exit_code != 0


def test_ui_requires_token_for_remote_mode() -> None:
    result = CliRunner().invoke(
        cli_app, ["workbench", "--allow-remote", "--no-browser"], env={"COLUMNS": "160"}
    )
    assert result.exit_code != 0
    assert "requires --token" in unstyle(result.stdout + getattr(result, "stderr", ""))


def test_mia_discover_bundle_is_separate_and_packaged(tmp_path: Path) -> None:
    with TestClient(create_app(_config(tmp_path), ui_variant="discover")) as client:
        index = client.get("/")
        assert index.status_code == 200
        assert "MIA Discover" in index.text
        assets = [item for item in index.text.split('"') if item.startswith("/assets/")]
        scripts = [item for item in assets if item.endswith(".js")]
        assert scripts
        javascript = "\n".join(client.get(item).text for item in scripts)
        assert "Search public sources" in javascript
        assert "Start platform" in javascript
        assert "Explain with AI" in javascript
        assert "Unlimited local searches" not in javascript
        assert "Results built for scanning" not in javascript
        icon = client.get("/mia-discover-icon.svg")
        assert icon.status_code == 200
        assert icon.headers["content-type"].startswith("image/svg+xml")
        assert icon.text.lstrip().startswith("<svg")
        manifest = client.get("/site.webmanifest")
        assert manifest.status_code == 200
        assert manifest.headers["content-type"].startswith("application/manifest+json")


def test_unknown_ui_variant_is_rejected(tmp_path: Path) -> None:
    import pytest

    with pytest.raises(ValueError, match="ui_variant"):
        create_app(_config(tmp_path), ui_variant="unknown")


def test_web_health_static_and_empty_overview(tmp_path: Path) -> None:
    with TestClient(create_app(_config(tmp_path))) as client:
        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.json()["version"] == "4.2.0a9"
        overview = client.get("/api/overview")
        assert overview.status_code == 200
        assert overview.json()["stats"]["cases"] == 0
        index = client.get("/")
        assert index.status_code == 200
        assert "MIA" in index.text


def test_deep_case_can_be_created_and_opened_from_ui(tmp_path: Path) -> None:
    with TestClient(create_app(_config(tmp_path))) as client:
        response = client.post(
            "/api/cases/deep",
            json={
                "name": "UI smoke case",
                "workflow": "identity",
                "profile": "quick",
                "verify_profiles": False,
                "enable_pivoting": False,
                "include_tools": ["hashid"],
                "seeds": [
                    {
                        "target": "5d41402abc4b2a76b9719d911017c592",
                        "target_type": "hash",
                        "label": "Known test hash",
                    }
                ],
            },
        )
        assert response.status_code == 200
        operation = _wait(client, response.json()["operation_id"])
        assert operation["status"] == "completed", operation
        case_id = operation["result"]["case_id"]
        detail = client.get(f"/api/cases/{case_id}")
        assert detail.status_code == 200
        payload = detail.json()
        assert payload["case"]["name"] == "UI smoke case"
        assert payload["nodes"]
        cases = client.get("/api/cases").json()
        assert cases[0]["case_id"] == case_id


def test_remote_api_token_is_enforced(tmp_path: Path) -> None:
    app = create_app(_config(tmp_path), allow_remote=True, access_token="secret-token")
    with TestClient(app) as client:
        assert client.get("/api/health").status_code == 401
        assert client.get("/api/health", headers={"x-mia-token": "secret-token"}).status_code == 200


def test_ui_bundle_is_beginner_first_and_websocket_backend_is_available(tmp_path: Path) -> None:
    import websockets  # noqa: F401

    with TestClient(create_app(_config(tmp_path))) as client:
        index = client.get("/")
        assert index.status_code == 200
        assets = [item for item in index.text.split('"') if item.startswith("/assets/")]
        scripts = [item for item in assets if item.endswith(".js")]
        assert scripts
        javascript = "\n".join(client.get(item).text for item in scripts)
        assert "Start a search" in javascript
        assert "Verify and compare" in javascript
        assert "Confirm external provider use" in javascript
        assert client.get("/mia-workbench-icon.svg").status_code == 200


def test_guided_review_uses_local_fallback_and_updates_case(tmp_path: Path) -> None:
    with TestClient(create_app(_config(tmp_path))) as client:
        response = client.post(
            "/api/cases/deep",
            json={
                "name": "Guided review case",
                "workflow": "identity",
                "profile": "quick",
                "verify_profiles": False,
                "enable_pivoting": False,
                "include_tools": ["hashid"],
                "seeds": [
                    {
                        "target": "5d41402abc4b2a76b9719d911017c592",
                        "target_type": "hash",
                    }
                ],
            },
        )
        created = _wait(client, response.json()["operation_id"])
        assert created["status"] == "completed", created
        case_id = created["result"]["case_id"]

        guided = client.post(
            f"/api/cases/{case_id}/guided-review",
            json={
                "use_ai": True,
                "provider": "local",
                "depth": "standard",
                "thinking_level": "high",
            },
        )
        assert guided.status_code == 200
        operation = _wait(client, guided.json()["operation_id"])
        assert operation["status"] == "completed", operation
        assert operation["result"]["provider"] == "local"
        detail = client.get(f"/api/cases/{case_id}").json()
        assert detail["analysis"] is not None


def test_external_ai_requires_explicit_cost_confirmation(tmp_path: Path, monkeypatch) -> None:
    import mia.web.app as web_app

    monkeypatch.setattr(
        web_app,
        "_provider_rows",
        lambda config: [
            {
                "provider": "local",
                "default": False,
                "model": "deterministic",
                "endpoint": "offline",
                "thinking_level": "deterministic",
                "credential": "not required",
                "ready": True,
                "external": False,
                "may_charge": False,
                "automatic": False,
                "data_destination": "this computer",
            },
            {
                "provider": "gemini",
                "default": True,
                "model": "test-model",
                "endpoint": "Gemini API",
                "thinking_level": "high",
                "credential": "keyring",
                "ready": True,
                "external": True,
                "may_charge": True,
                "automatic": False,
                "data_destination": "Gemini API",
            },
        ],
    )
    with TestClient(create_app(_config(tmp_path))) as client:
        response = client.post(
            "/api/cases/deep",
            json={
                "name": "Cost guard",
                "workflow": "identity",
                "profile": "quick",
                "verify_profiles": False,
                "enable_pivoting": False,
                "include_tools": ["hashid"],
                "seeds": [{"target": "5d41402abc4b2a76b9719d911017c592", "target_type": "hash"}],
            },
        )
        created = _wait(client, response.json()["operation_id"])
        case_id = created["result"]["case_id"]
        blocked = client.post(
            f"/api/cases/{case_id}/guided-review", json={"use_ai": True, "provider": "gemini"}
        )
        assert blocked.status_code == 400
        assert "confirm_external_cost=true" in blocked.json()["detail"]


def test_direct_analysis_also_requires_external_cost_confirmation(
    tmp_path: Path, monkeypatch
) -> None:
    import mia.web.app as web_app

    monkeypatch.setattr(
        web_app,
        "_provider_rows",
        lambda config: [
            {
                "provider": "local",
                "default": False,
                "model": "deterministic",
                "endpoint": "offline",
                "thinking_level": "deterministic",
                "credential": "not required",
                "ready": True,
                "external": False,
                "may_charge": False,
                "automatic": False,
                "data_destination": "this computer",
            },
            {
                "provider": "gemini",
                "default": True,
                "model": "test-model",
                "endpoint": "https://generativelanguage.googleapis.com",
                "thinking_level": "high",
                "credential": "keyring",
                "ready": True,
                "external": True,
                "may_charge": True,
                "automatic": False,
                "data_destination": "Gemini API",
            },
        ],
    )
    with TestClient(create_app(_config(tmp_path))) as client:
        response = client.post(
            "/api/cases/deep",
            json={
                "name": "Analysis cost guard",
                "workflow": "identity",
                "profile": "quick",
                "verify_profiles": False,
                "enable_pivoting": False,
                "include_tools": ["hashid"],
                "seeds": [{"target": "5d41402abc4b2a76b9719d911017c592", "target_type": "hash"}],
            },
        )
        created = _wait(client, response.json()["operation_id"])
        case_id = created["result"]["case_id"]
        blocked = client.post(f"/api/cases/{case_id}/analyze", json={"provider": "gemini"})
        assert blocked.status_code == 400
        assert "confirm_external_cost=true" in blocked.json()["detail"]


def test_operation_websocket_streams_a_snapshot(tmp_path: Path) -> None:
    with TestClient(create_app(_config(tmp_path))) as client:
        response = client.post(
            "/api/cases/deep",
            json={
                "name": "WebSocket case",
                "workflow": "identity",
                "profile": "quick",
                "verify_profiles": False,
                "enable_pivoting": False,
                "include_tools": ["hashid"],
                "seeds": [
                    {
                        "target": "5d41402abc4b2a76b9719d911017c592",
                        "target_type": "hash",
                    }
                ],
            },
        )
        operation_id = response.json()["operation_id"]
        with client.websocket_connect(f"/ws/operations/{operation_id}") as socket:
            payload = socket.receive_json()
            assert payload["type"] == "snapshot"
            assert payload["operation"]["operation_id"] == operation_id


def test_guided_review_falls_back_to_local_when_remote_ai_fails(
    tmp_path: Path, monkeypatch
) -> None:
    import mia.web.app as web_app
    from mia.assistant import InvestigationAssistant

    original_analyze = InvestigationAssistant.analyze

    async def failing_remote(self, *args, provider=None, **kwargs):  # type: ignore[no-untyped-def]
        if provider == "gemini":
            raise RuntimeError("simulated provider outage")
        return await original_analyze(self, *args, provider=provider, **kwargs)

    monkeypatch.setattr(
        web_app,
        "_provider_rows",
        lambda config: [
            {
                "provider": "local",
                "default": False,
                "model": "deterministic",
                "endpoint": "offline",
                "thinking_level": "deterministic",
                "credential": "not required",
                "ready": True,
                "external": False,
                "may_charge": False,
                "automatic": False,
                "data_destination": "this computer",
            },
            {
                "provider": "gemini",
                "default": True,
                "model": "test-model",
                "endpoint": "test",
                "thinking_level": "high",
                "credential": "keyring",
                "ready": True,
                "external": True,
                "may_charge": True,
                "automatic": False,
                "data_destination": "Gemini API",
            },
        ],
    )
    monkeypatch.setattr(InvestigationAssistant, "analyze", failing_remote)

    with TestClient(create_app(_config(tmp_path))) as client:
        response = client.post(
            "/api/cases/deep",
            json={
                "name": "AI fallback case",
                "workflow": "identity",
                "profile": "quick",
                "verify_profiles": False,
                "enable_pivoting": False,
                "include_tools": ["hashid"],
                "seeds": [
                    {
                        "target": "5d41402abc4b2a76b9719d911017c592",
                        "target_type": "hash",
                    }
                ],
            },
        )
        created = _wait(client, response.json()["operation_id"])
        case_id = created["result"]["case_id"]
        guided = client.post(
            f"/api/cases/{case_id}/guided-review",
            json={
                "use_ai": True,
                "provider": "gemini",
                "confirm_external_cost": True,
                "depth": "standard",
                "thinking_level": "high",
            },
        )
        operation = _wait(client, guided.json()["operation_id"])
        assert operation["status"] == "completed", operation
        assert operation["result"]["provider"] == "local"
        assert "simulated provider outage" in operation["result"]["ai_warning"]
