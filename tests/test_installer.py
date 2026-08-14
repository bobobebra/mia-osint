from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from mia.config import load_config
from mia.models import PluginContext, ScanProfile, TargetType
from mia.plugins.holehe import HolehePlugin
from mia.plugins.spiderfoot import SpiderFootPlugin

ROOT = Path(__file__).resolve().parents[1]


def _context(tmp_path: Path, plugin: str, target: str, target_type: TargetType) -> PluginContext:
    raw_dir = tmp_path / "raw" / plugin
    raw_dir.mkdir(parents=True)
    return PluginContext(
        scan_id="scan",
        target=target,
        target_type=target_type,
        profile=ScanProfile.DEEP,
        scan_dir=tmp_path,
        raw_dir=raw_dir,
        timeout_seconds=30,
    )


def _dry_run(tmp_path: Path, manager: str = "none", *, path: str | None = None) -> str:
    env = {
        **os.environ,
        "HOME": str(tmp_path),
        "PATH": path or os.environ.get("PATH", ""),
    }
    completed = subprocess.run(
        [
            "bash",
            str(ROOT / "install.sh"),
            "--dry-run",
            "--yes",
            "--package-manager",
            manager,
        ],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    assert not tmp_path.exists() or not any(tmp_path.iterdir())
    return completed.stdout


def test_installer_shell_syntax() -> None:
    subprocess.run(["bash", "-n", str(ROOT / "install.sh")], check=True)
    subprocess.run(["bash", "-n", str(ROOT / "uninstall.sh")], check=True)
    subprocess.run(["bash", "-n", str(ROOT / "install-mia.sh")], check=True)
    subprocess.run(["bash", "-n", str(ROOT / "scripts" / "build_linux_installer.sh")], check=True)


def test_default_installer_delegates_core_group_to_package_manager(tmp_path: Path) -> None:
    output = _dry_run(tmp_path)
    assert "pkg install" in output
    assert "--group core" in output
    assert "uv venv --python" in output
    assert "desktop install" in output


@pytest.mark.parametrize(
    ("manager", "expected"),
    [
        ("apt", "apt-get install -y"),
        ("dnf", "dnf install -y"),
        ("pacman", "pacman -Sy --needed --noconfirm"),
        ("zypper", "zypper --non-interactive install"),
        ("apk", "apk add --no-cache"),
        ("brew", "brew install python@3.11"),
        ("none", "Selected package manager: none"),
    ],
)
def test_cross_distribution_package_manager_dry_runs(
    tmp_path: Path, manager: str, expected: str
) -> None:
    output = _dry_run(tmp_path / manager, manager)
    assert expected in output


def test_default_config_uses_installer_wrappers(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("MIA_CONFIG", raising=False)
    config = load_config()
    assert config.tool("spiderfoot").executable == "mia-spiderfoot"
    assert config.tool("holehe").executable == "mia-holehe-runner"


def test_spiderfoot_wrapper_is_invoked_directly(tmp_path: Path) -> None:
    context = _context(tmp_path, "spiderfoot", "example.com", TargetType.DOMAIN)
    command = SpiderFootPlugin().build_command(context, load_config(), "/tmp/mia-spiderfoot")
    assert command[:4] == ["/tmp/mia-spiderfoot", "-s", "example.com", "-o"]


def test_holehe_structured_wrapper_command(tmp_path: Path, monkeypatch) -> None:
    plugin = HolehePlugin()
    monkeypatch.setattr(plugin, "module_available", lambda: False)
    context = _context(tmp_path, "holehe", "person@example.com", TargetType.EMAIL)
    context.extra_args = ["--timeout", "9"]
    command = plugin.build_command(context, load_config(), "/tmp/mia-holehe-runner")
    assert command == ["/tmp/mia-holehe-runner", "person@example.com", "--timeout", "9"]


def test_spiderfoot_compatibility_requirements(tmp_path: Path) -> None:
    from scripts.prepare_spiderfoot_requirements import prepare

    source = tmp_path / "requirements.txt"
    destination = tmp_path / "requirements-mia.txt"
    source.write_text("requests>=2,<3\npyyaml>=5.4.1,<6\n", encoding="utf-8")
    prepare(source, destination)
    output = destination.read_text(encoding="utf-8")
    assert "requests>=2,<3" in output
    assert "pyyaml>=6.0,<7" in output
    assert "pyyaml>=5.4.1,<6" not in output


def test_spiderfoot_quick_profile_does_not_use_invalid_strict_mode(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("MIA_CONFIG", raising=False)
    config = load_config()
    assert "-x" not in config.tool("spiderfoot").profile_args["quick"]


def test_installer_uses_existing_home_bin_on_path(tmp_path: Path) -> None:
    custom_path = f"{tmp_path / 'bin'}:{os.environ.get('PATH', '')}"
    output = _dry_run(tmp_path, "none", path=custom_path)
    assert str(tmp_path / "bin" / "mia") in output


def test_installer_default_core_group_is_not_lost_to_bash_groups_variable(tmp_path: Path) -> None:
    output = _dry_run(tmp_path, "none")
    assert "--group core" in output


def _write_fake_uv(path: Path, *, fail_install: bool = False) -> None:
    script = f'''#!/usr/bin/env bash
set -euo pipefail
if [[ "$1" == "venv" ]]; then
  target="${{@: -1}}"
  mkdir -p "$target/bin"
  printf '#!/usr/bin/env bash\nexec "{os.environ.get("PYTHON", "python3")}" "$@"\n' > "$target/bin/python"
  chmod +x "$target/bin/python"
  exit 0
fi
if [[ "$1" == "pip" && "$2" == "install" ]]; then
  {"exit 42" if fail_install else ":"}
  python_path=""
  while (($#)); do
    if [[ "$1" == "--python" ]]; then shift; python_path="$1"; break; fi
    shift
  done
  bin_dir="$(dirname "$python_path")"
  cat > "$bin_dir/mia" <<'EOF'
#!/usr/bin/env bash
case "${{1:-}}" in
  --version|version) echo 4.2.0a10 ;;
  doctor) echo 'doctor ok' ;;
  *) echo 'fake mia' ;;
esac
EOF
  chmod +x "$bin_dir/mia"
  exit 0
fi
if [[ "$1" == "pip" && "$2" == "check" ]]; then
  exit 0
fi
exit 2
'''
    path.write_text(script, encoding="utf-8")
    path.chmod(0o755)


def test_installer_upgrades_existing_environment_without_embedded_pip(tmp_path: Path) -> None:
    home = tmp_path / "home"
    state = home / ".local" / "share" / "mia"
    venv = state / "venv"
    bin_dir = home / ".local" / "bin"
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir(parents=True)
    _write_fake_uv(fake_bin / "uv")

    (venv / "bin").mkdir(parents=True)
    old_mia = venv / "bin" / "mia"
    old_mia.write_text("#!/usr/bin/env bash\necho 3.3.0a1\n", encoding="utf-8")
    old_mia.chmod(0o755)
    bin_dir.mkdir(parents=True)
    (bin_dir / "mia").symlink_to(old_mia)

    env = {
        **os.environ,
        "HOME": str(home),
        "PATH": f"{fake_bin}:{bin_dir}:{os.environ.get('PATH', '')}",
        "MIA_PACKAGE_MANAGER": "none",
        "MIA_STATE_DIR": str(state),
        "MIA_BIN_DIR": str(bin_dir),
        "MIA_INSTALL_LOG_DIR": str(home / ".local" / "state" / "mia"),
    }
    completed = subprocess.run(
        [
            "bash",
            str(ROOT / "install.sh"),
            "--mia-only",
            "--yes",
            "--skip-system-packages",
        ],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    assert "Installed and verified MIA 4.2.0a10" in completed.stdout
    version = subprocess.run(
        [str(bin_dir / "mia"), "--version"], check=True, capture_output=True, text=True
    )
    assert version.stdout.strip() == "4.2.0a10"
    assert not (state / "venv.previous").exists()


def test_installer_restores_previous_environment_when_upgrade_fails(tmp_path: Path) -> None:
    home = tmp_path / "home"
    state = home / ".local" / "share" / "mia"
    venv = state / "venv"
    bin_dir = home / ".local" / "bin"
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir(parents=True)
    _write_fake_uv(fake_bin / "uv", fail_install=True)

    (venv / "bin").mkdir(parents=True)
    old_mia = venv / "bin" / "mia"
    old_mia.write_text("#!/usr/bin/env bash\necho 3.3.0a1\n", encoding="utf-8")
    old_mia.chmod(0o755)
    bin_dir.mkdir(parents=True)
    (bin_dir / "mia").symlink_to(old_mia)

    env = {
        **os.environ,
        "HOME": str(home),
        "PATH": f"{fake_bin}:{bin_dir}:{os.environ.get('PATH', '')}",
        "MIA_PACKAGE_MANAGER": "none",
        "MIA_STATE_DIR": str(state),
        "MIA_BIN_DIR": str(bin_dir),
        "MIA_INSTALL_LOG_DIR": str(home / ".local" / "state" / "mia"),
    }
    completed = subprocess.run(
        [
            "bash",
            str(ROOT / "install.sh"),
            "--mia-only",
            "--yes",
            "--skip-system-packages",
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert completed.returncode != 0
    assert "Restored the previous MIA environment" in completed.stderr
    version = subprocess.run(
        [str(bin_dir / "mia"), "--version"], check=True, capture_output=True, text=True
    )
    assert version.stdout.strip() == "3.3.0a1"


def test_one_file_linux_installer_builds_and_forwards_arguments(tmp_path: Path) -> None:
    output = tmp_path / "MIA-Linux-Installer.run"
    subprocess.run(
        ["bash", str(ROOT / "scripts" / "build_linux_installer.sh"), str(output)],
        check=True,
        capture_output=True,
        text=True,
    )
    assert output.is_file()
    assert os.access(output, os.X_OK)
    assert b"__MIA_PAYLOAD_BELOW__" in output.read_bytes()

    home = tmp_path / "home"
    home.mkdir()
    completed = subprocess.run(
        [
            "bash",
            str(output),
            "--dry-run",
            "--yes",
            "--mia-only",
            "--no-desktop",
            "--package-manager",
            "none",
        ],
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, "HOME": str(home)},
    )
    assert "MIA one-file Linux installer" in completed.stdout
    assert "Dry run complete" in completed.stdout


def test_friendly_installer_delegates_to_bundled_source_installer(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    completed = subprocess.run(
        [
            "bash",
            str(ROOT / "install-mia.sh"),
            "--dry-run",
            "--yes",
            "--mia-only",
            "--no-desktop",
            "--package-manager",
            "none",
        ],
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, "HOME": str(home)},
    )
    assert "Dry run complete" in completed.stdout
