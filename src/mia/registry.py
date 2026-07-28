from __future__ import annotations

import importlib
import importlib.util
import inspect
import pkgutil
from importlib.metadata import entry_points
from pathlib import Path

from mia.exceptions import PluginError
from mia.plugin import BasePlugin
from mia.plugin_sdk import CommunityPluginManager


class PluginRegistry:
    def __init__(self) -> None:
        self._plugins: dict[str, BasePlugin] = {}

    def register(self, plugin: BasePlugin) -> None:
        if not plugin.plugin_id or plugin.plugin_id == "base":
            raise PluginError("plugin_id must be a non-empty stable identifier")
        if plugin.plugin_id in self._plugins:
            existing = self._plugins[plugin.plugin_id]
            raise PluginError(
                f"duplicate plugin id {plugin.plugin_id!r}: {existing.__class__.__name__} and {plugin.__class__.__name__}"
            )
        self._plugins[plugin.plugin_id] = plugin

    def discover_builtins(self) -> None:
        package = importlib.import_module("mia.plugins")
        for module_info in pkgutil.iter_modules(package.__path__, f"{package.__name__}."):
            if module_info.name.rsplit(".", 1)[-1].startswith("_"):
                continue
            module = importlib.import_module(module_info.name)
            self._register_from_module(module)

    def _register_from_module(self, module: object) -> None:
        explicit = getattr(module, "PLUGIN_CLASS", None)
        explicit_many = getattr(module, "PLUGIN_CLASSES", None)
        classes: list[type[BasePlugin]] = []
        if explicit is not None:
            classes.append(explicit)
        if explicit_many is not None:
            classes.extend(explicit_many)
        if explicit is None and explicit_many is None:
            for _, candidate in inspect.getmembers(module, inspect.isclass):
                if (
                    candidate is not BasePlugin
                    and issubclass(candidate, BasePlugin)
                    and candidate.__module__ == getattr(module, "__name__", "")
                    and not inspect.isabstract(candidate)
                ):
                    classes.append(candidate)
        for plugin_class in classes:
            plugin = plugin_class()
            if not isinstance(plugin, BasePlugin):
                raise PluginError(f"{plugin_class!r} did not produce a BasePlugin")
            self.register(plugin)

    def discover_entry_points(self) -> None:
        for point in entry_points(group="mia.plugins"):
            loaded = point.load()
            plugin = loaded() if inspect.isclass(loaded) else loaded
            if not isinstance(plugin, BasePlugin):
                raise PluginError(f"entry point {point.name!r} did not produce a BasePlugin")
            self.register(plugin)

    def discover_community(self, directory: Path | None) -> None:
        if directory is None or not directory.exists():
            return
        manager = CommunityPluginManager(directory)
        for manifest, plugin_dir in manager.list():
            entrypoint = plugin_dir / manifest.entrypoint
            validation = manager.validate(plugin_dir)
            if not validation["valid"]:
                continue
            spec = importlib.util.spec_from_file_location(
                f"mia_community_{manifest.plugin_id}", entrypoint
            )
            if spec is None or spec.loader is None:
                continue
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            self._register_from_module(module)

    @classmethod
    def discover(cls, user_plugins_dir: Path | None = None) -> PluginRegistry:
        registry = cls()
        registry.discover_builtins()
        registry.discover_entry_points()
        registry.discover_community(user_plugins_dir)
        return registry

    def get(self, plugin_id: str) -> BasePlugin:
        try:
            return self._plugins[plugin_id]
        except KeyError as exc:
            raise PluginError(f"unknown plugin: {plugin_id}") from exc

    def all(self) -> list[BasePlugin]:
        return sorted(self._plugins.values(), key=lambda item: item.plugin_id)

    def ids(self) -> list[str]:
        return sorted(self._plugins)
