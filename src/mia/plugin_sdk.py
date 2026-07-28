from __future__ import annotations

import importlib.metadata
import importlib.util
import shutil
from pathlib import Path
from typing import Any

import yaml
from packaging.requirements import InvalidRequirement, Requirement
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version
from pydantic import BaseModel, Field, field_validator

from mia import __version__
from mia.exceptions import PluginError
from mia.utils import atomic_write_text


class PluginManifest(BaseModel):
    manifest_version: str = "1"
    plugin_id: str
    name: str
    version: str = "0.1.0"
    description: str = ""
    entrypoint: str = "plugin.py"
    requires_mia: str = ">=4.0.0a1,<5"
    license: str = "MIT"
    homepage: str | None = None
    target_types: list[str] = Field(default_factory=list)
    package_dependencies: list[str] = Field(default_factory=list)
    python_dependencies: list[str] = Field(default_factory=list)
    api_services: list[str] = Field(default_factory=list)

    @field_validator("plugin_id")
    @classmethod
    def valid_id(cls, value: str) -> str:
        import re

        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{1,63}", value):
            raise ValueError("plugin_id must contain only lowercase letters, digits, _ or -")
        return value


class CommunityPluginManager:
    def __init__(self, plugin_dir: Path) -> None:
        self.plugin_dir = plugin_dir.expanduser()
        self.plugin_dir.mkdir(parents=True, exist_ok=True, mode=0o700)

    @staticmethod
    def load_manifest(directory: Path) -> PluginManifest:
        path = directory / "manifest.yaml"
        if not path.exists():
            raise PluginError(f"plugin manifest not found: {path}")
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            return PluginManifest.model_validate(data)
        except (OSError, yaml.YAMLError, ValueError) as exc:
            raise PluginError(f"invalid plugin manifest {path}: {exc}") from exc

    def list(self) -> list[tuple[PluginManifest, Path]]:
        plugins = []
        for directory in sorted(self.plugin_dir.iterdir()):
            if not directory.is_dir() or not (directory / "manifest.yaml").exists():
                continue
            try:
                plugins.append((self.load_manifest(directory), directory))
            except PluginError:
                continue
        return plugins

    def validate(self, directory: Path) -> dict[str, Any]:
        directory = directory.expanduser().resolve()
        manifest = self.load_manifest(directory)
        entrypoint = directory / manifest.entrypoint
        errors: list[str] = []
        warnings: list[str] = []
        dependencies = self.dependency_status(manifest)
        if not dependencies["mia_compatible"]:
            errors.append(
                f"plugin requires MIA {manifest.requires_mia}, but the running version is {__version__}"
            )
        for item in dependencies["python"]:
            if not item["satisfied"]:
                warnings.append(
                    f"Python dependency is not satisfied: {item['requirement']} ({item['status']})"
                )
        if not entrypoint.is_file():
            errors.append(f"entrypoint not found: {entrypoint}")
        if not (directory / "README.md").exists():
            warnings.append("README.md is missing")
        if not (directory / "tests").exists():
            warnings.append("tests/ directory is missing")
        if not manifest.target_types:
            warnings.append("manifest target_types is empty")
        if entrypoint.exists():
            try:
                spec = importlib.util.spec_from_file_location(
                    f"mia_community_validate_{manifest.plugin_id}", entrypoint
                )
                if spec is None or spec.loader is None:
                    raise ImportError("unable to create module spec")
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                if not hasattr(module, "PLUGIN_CLASS") and not hasattr(module, "PLUGIN_CLASSES"):
                    errors.append("entrypoint must expose PLUGIN_CLASS or PLUGIN_CLASSES")
            except Exception as exc:
                errors.append(f"entrypoint import failed: {type(exc).__name__}: {exc}")
        return {
            "valid": not errors,
            "manifest": manifest.model_dump(mode="json"),
            "path": str(directory),
            "errors": errors,
            "warnings": warnings,
            "dependencies": dependencies,
            "mia_version": __version__,
        }

    @staticmethod
    def dependency_status(manifest: PluginManifest) -> dict[str, Any]:
        try:
            mia_compatible = Version(__version__) in SpecifierSet(manifest.requires_mia)
        except (InvalidVersion, InvalidSpecifier):
            mia_compatible = False
        python_status: list[dict[str, Any]] = []
        for raw in manifest.python_dependencies:
            try:
                requirement = Requirement(raw)
                installed = importlib.metadata.version(requirement.name)
                satisfied = not requirement.specifier or Version(installed) in requirement.specifier
                status = (
                    installed
                    if satisfied
                    else f"installed {installed}, outside {requirement.specifier}"
                )
            except importlib.metadata.PackageNotFoundError:
                satisfied = False
                status = "not installed"
            except (InvalidRequirement, InvalidVersion) as exc:
                satisfied = False
                status = f"invalid requirement: {exc}"
            python_status.append({"requirement": raw, "satisfied": satisfied, "status": status})
        return {
            "mia_compatible": mia_compatible,
            "requires_mia": manifest.requires_mia,
            "python": python_status,
            "packages": list(manifest.package_dependencies),
            "api_services": list(manifest.api_services),
        }

    def install(self, source: Path, *, replace: bool = False) -> Path:
        source = source.expanduser().resolve()
        validation = self.validate(source)
        if not validation["valid"]:
            raise PluginError("plugin validation failed: " + "; ".join(validation["errors"]))
        manifest = PluginManifest.model_validate(validation["manifest"])
        destination = self.plugin_dir / manifest.plugin_id
        if destination.exists():
            if not replace:
                raise PluginError(f"plugin already installed: {manifest.plugin_id}")
            shutil.rmtree(destination)
        shutil.copytree(
            source,
            destination,
            ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", ".git"),
        )
        return destination

    def uninstall(self, plugin_id: str) -> bool:
        destination = self.plugin_dir / plugin_id
        if not destination.exists():
            return False
        shutil.rmtree(destination)
        return True

    def create(self, plugin_id: str, destination: Path | None = None) -> Path:
        manifest = PluginManifest(
            plugin_id=plugin_id,
            name=plugin_id.replace("-", " ").replace("_", " ").title(),
            description="Community MIA plugin",
            target_types=["username"],
        )
        root = (destination or Path.cwd() / plugin_id).expanduser()
        if root.exists() and any(root.iterdir()):
            raise PluginError(f"destination is not empty: {root}")
        root.mkdir(parents=True, exist_ok=True)
        atomic_write_text(
            root / "manifest.yaml",
            yaml.safe_dump(manifest.model_dump(mode="json"), sort_keys=False),
        )
        atomic_write_text(
            root / "plugin.py",
            '''from __future__ import annotations\n\nfrom datetime import UTC, datetime\n\nfrom mia.config import AppConfig\nfrom mia.models import Finding, PluginContext, PluginRunResult, PluginRunStatus, TargetType\nfrom mia.plugin import BasePlugin\nfrom mia.process import ProcessRunner\n\n\nclass ExamplePlugin(BasePlugin):\n    plugin_id = "'''
            + plugin_id
            + """"\n    name = "Example community plugin"\n    description = "Replace this implementation with a lawful public-source integration."\n    target_types = frozenset({TargetType.USERNAME})\n    network_required = False\n\n    async def execute(self, context: PluginContext, config: AppConfig, runner: ProcessRunner) -> PluginRunResult:\n        del config, runner\n        started = datetime.now(UTC)\n        finding = Finding(\n            plugin_id=self.plugin_id,\n            category="Example",\n            kind="example",\n            title="Example finding",\n            value=context.target,\n            source_confidence=0.2,\n            attributes={"replace_me": True},\n        )\n        finished = datetime.now(UTC)\n        return PluginRunResult(\n            plugin_id=self.plugin_id,\n            plugin_name=self.name,\n            status=PluginRunStatus.SUCCESS,\n            started_at=started,\n            finished_at=finished,\n            duration_seconds=(finished-started).total_seconds(),\n            findings=[finding],\n        )\n\n\nPLUGIN_CLASS = ExamplePlugin\n""",
        )
        atomic_write_text(
            root / "README.md",
            f"# {manifest.name}\n\nGenerated by `mia plugin create {plugin_id}`.\n\n"
            "Document data sources, authorization assumptions, output fields, false-positive behavior, and tests before publishing.\n",
        )
        tests = root / "tests"
        tests.mkdir(exist_ok=True)
        atomic_write_text(
            tests / "test_plugin.py",
            "from plugin import ExamplePlugin\n\n\ndef test_plugin_id():\n    assert ExamplePlugin.plugin_id\n",
        )
        return root
