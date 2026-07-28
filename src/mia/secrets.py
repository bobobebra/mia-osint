from __future__ import annotations

import contextlib
import os

import keyring
from keyring.errors import KeyringError

from mia.config import AppConfig
from mia.exceptions import ConfigurationError
from mia.platform_support import platform_paths
from mia.utils import atomic_write_text

SERVICE_NAME = "mia-osint"


class SecretStore:
    """Environment-first secret storage with OS keyring support.

    Plaintext files are never used unless the caller explicitly requests the
    insecure fallback. This keeps API keys out of MIA YAML, reports, commands,
    and package state.
    """

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.insecure_path = platform_paths().config_dir / "secrets.env"

    @staticmethod
    def key_name(service: str) -> str:
        return f"api:{service.lower()}"

    def env_name(self, service: str) -> str:
        api = self.config.api(service)
        return api.key_env or f"MIA_{service.upper().replace('-', '_')}_API_KEY"

    def env_names(self, service: str) -> list[str]:
        api = self.config.api(service)
        names = [self.env_name(service), *api.key_env_aliases]
        return list(dict.fromkeys(name for name in names if name))

    def get(self, service: str) -> str | None:
        for env_name in self.env_names(service):
            if value := os.getenv(env_name):
                return value.strip()
        try:
            value = keyring.get_password(SERVICE_NAME, self.key_name(service))
        except KeyringError:
            value = None
        if value:
            return value.strip()
        if self.insecure_path.exists():
            accepted = set(self.env_names(service))
            for line in self.insecure_path.read_text(encoding="utf-8").splitlines():
                if not line or line.lstrip().startswith("#") or "=" not in line:
                    continue
                name, value = line.split("=", 1)
                if name.strip() in accepted:
                    return value.strip().strip('"').strip("'")
        return None

    def set(self, service: str, value: str, *, insecure_file: bool = False) -> str:
        if not value.strip():
            raise ConfigurationError("API key cannot be empty")
        if insecure_file:
            self._set_insecure_file(self.env_name(service), value.strip())
            return str(self.insecure_path)
        try:
            keyring.set_password(SERVICE_NAME, self.key_name(service), value.strip())
        except KeyringError as exc:
            raise ConfigurationError(
                "No usable OS keyring is available. Set the documented environment variable "
                f"{self.env_name(service)} instead, or repeat with --insecure-file to use a 0600 plaintext file."
            ) from exc
        return "system keyring"

    def delete(self, service: str) -> bool:
        deleted = False
        try:
            keyring.delete_password(SERVICE_NAME, self.key_name(service))
            deleted = True
        except (KeyringError, PasswordDeleteError):
            pass
        if self.insecure_path.exists():
            env_names = self.env_names(service)
            lines = self.insecure_path.read_text(encoding="utf-8").splitlines()
            filtered = [
                line
                for line in lines
                if not any(line.startswith(f"{env_name}=") for env_name in env_names)
            ]
            if filtered != lines:
                atomic_write_text(
                    self.insecure_path, "\n".join(filtered) + ("\n" if filtered else "")
                )
                deleted = True
        return deleted

    def source(self, service: str) -> str:
        for env_name in self.env_names(service):
            if os.getenv(env_name):
                return f"environment ({env_name})"
        try:
            if keyring.get_password(SERVICE_NAME, self.key_name(service)):
                return "system keyring"
        except KeyringError:
            pass
        if self.insecure_path.exists():
            for line in self.insecure_path.read_text(encoding="utf-8").splitlines():
                if any(line.startswith(f"{name}=") for name in self.env_names(service)):
                    return f"insecure file ({self.insecure_path})"
        return "not configured"

    def _set_insecure_file(self, env_name: str, value: str) -> None:
        self.insecure_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        lines: list[str] = []
        if self.insecure_path.exists():
            lines = [
                line
                for line in self.insecure_path.read_text(encoding="utf-8").splitlines()
                if not line.startswith(f"{env_name}=")
            ]
        escaped = value.replace("'", "'\"'\"'")
        lines.append(f"{env_name}='{escaped}'")
        atomic_write_text(self.insecure_path, "\n".join(lines) + "\n", mode=0o600)
        with contextlib.suppress(OSError):
            self.insecure_path.chmod(0o600)


try:
    from keyring.errors import PasswordDeleteError
except ImportError:  # pragma: no cover
    PasswordDeleteError = KeyringError
