from click import unstyle
from typer.testing import CliRunner

from mia.cli import app

runner = CliRunner()


def test_version() -> None:
    for arguments in (["version"], ["--version"]):
        result = runner.invoke(app, arguments)
        assert result.exit_code == 0
        assert "4.2.0a11" in result.stdout


def test_hash_command(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MIA_OUTPUT_DIR", str(tmp_path / "reports"))
    monkeypatch.setenv("MIA_STATE_DIR", str(tmp_path / "state"))
    result = runner.invoke(
        app,
        ["hash", "d41d8cd98f00b204e9800998ecf8427e", "--tool", "hashid", "--profile", "quick"],
    )
    assert result.exit_code == 0, result.stdout
    assert "normalized findings" in result.stdout


def test_default_profile_is_used_when_no_profile_is_given(tmp_path, monkeypatch) -> None:
    reports = tmp_path / "reports"
    monkeypatch.setenv("MIA_OUTPUT_DIR", str(reports))
    monkeypatch.setenv("MIA_STATE_DIR", str(tmp_path / "state"))

    result = runner.invoke(
        app,
        ["hash", "d41d8cd98f00b204e9800998ecf8427e", "--tool", "hashid"],
    )

    assert result.exit_code == 0, result.stdout
    report = next(reports.rglob("report.json"))
    assert '"profile": "default"' in report.read_text(encoding="utf-8")


def test_profile_shortcut_flags(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MIA_OUTPUT_DIR", str(tmp_path / "reports"))
    monkeypatch.setenv("MIA_STATE_DIR", str(tmp_path / "state"))
    digest = "d41d8cd98f00b204e9800998ecf8427e"

    quick = runner.invoke(app, ["hash", digest, "--tool", "hashid", "--quick"])
    deep = runner.invoke(app, ["hash", digest, "--tool", "hashid", "--deep"])
    explicit = runner.invoke(app, ["hash", digest, "--tool", "hashid", "--profile", "default"])

    assert quick.exit_code == 0, quick.stdout
    assert deep.exit_code == 0, deep.stdout
    assert explicit.exit_code == 0, explicit.stdout
    profiles = {
        __import__("json").loads(path.read_text(encoding="utf-8"))["profile"]
        for path in (tmp_path / "reports").rglob("report.json")
    }
    assert {"quick", "default", "deep"}.issubset(profiles)


def test_profile_shortcuts_are_mutually_exclusive() -> None:
    result = runner.invoke(
        app,
        ["hash", "d41d8cd98f00b204e9800998ecf8427e", "--quick", "--deep"],
    )
    assert result.exit_code == 2
    assert "Choose only one" in result.output


def test_profiles_command() -> None:
    result = runner.invoke(app, ["profiles"])
    assert result.exit_code == 0, result.stdout
    for profile in ("quick", "default", "deep", "all"):
        assert profile in result.stdout


def test_about_command_discloses_alpha_and_ai_assistance() -> None:
    result = runner.invoke(app, ["about"])
    assert result.exit_code == 0, result.stdout
    assert "early alpha" in result.stdout
    assert "vibe-coded" in result.stdout
    assert "AI assistance" in result.stdout


def test_package_catalog_cli_and_dry_run(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("MIA_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("MIA_BIN_DIR", str(tmp_path / "bin"))

    listed = runner.invoke(app, ["pkg", "list", "--group", "username", "--json"])
    assert listed.exit_code == 0, listed.stdout
    assert '"blackbird"' in listed.stdout
    assert '"integration"' in listed.stdout

    dry_run = runner.invoke(
        app,
        [
            "pkg",
            "install",
            "waymore",
            "--dry-run",
            "--yes",
            "--no-system",
            "--package-manager",
            "none",
        ],
    )
    assert dry_run.exit_code == 0, dry_run.stdout
    assert "would install waymore" in dry_run.stdout
    assert "planned commands" in dry_run.stdout
    assert "uv venv --python 3.12" in dry_run.stdout
    assert "Summary:" in dry_run.stdout
    assert "Duration" in dry_run.stdout
    assert not (tmp_path / "state").exists()


def test_package_commands_expose_quiet_progress_mode() -> None:
    for command in ("install", "uninstall", "update"):
        result = runner.invoke(app, ["pkg", command, "--help"], env={"COLUMNS": "160"})
        assert result.exit_code == 0, result.stdout
        assert "--quiet" in unstyle(result.stdout)


def test_package_quiet_and_verbose_are_mutually_exclusive(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("MIA_STATE_DIR", str(tmp_path / "state"))
    result = runner.invoke(
        app,
        [
            "--verbose",
            "pkg",
            "install",
            "waymore",
            "--dry-run",
            "--yes",
            "--quiet",
            "--no-system",
            "--package-manager",
            "none",
        ],
    )
    assert result.exit_code == 2
    assert "--quiet cannot be combined" in result.output


def test_mixed_package_requires_explicit_opt_in(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("MIA_STATE_DIR", str(tmp_path / "state"))
    blocked = runner.invoke(
        app,
        [
            "pkg",
            "install",
            "httpx",
            "--dry-run",
            "--yes",
            "--package-manager",
            "none",
        ],
    )
    assert blocked.exit_code == 2
    assert "--include-mixed" in blocked.output

    allowed = runner.invoke(
        app,
        [
            "pkg",
            "install",
            "httpx",
            "--dry-run",
            "--yes",
            "--include-mixed",
            "--package-manager",
            "none",
        ],
    )
    assert allowed.exit_code == 0, allowed.stdout
