from mia.registry import PluginRegistry


def test_builtin_discovery() -> None:
    registry = PluginRegistry.discover()
    assert {
        "maigret",
        "sherlock",
        "spiderfoot",
        "holehe",
        "exiftool",
        "whois",
        "dns",
        "hashid",
    }.issubset(set(registry.ids()))


def test_extended_plugins_are_discovered() -> None:
    registry = PluginRegistry()
    registry.discover_builtins()
    for plugin_id in (
        "subfinder",
        "assetfinder",
        "gau",
        "httpx",
        "dnstwist",
        "blackbird",
        "social-analyzer",
        "theharvester",
        "phoneinfoga",
    ):
        assert registry.get(plugin_id).plugin_id == plugin_id
