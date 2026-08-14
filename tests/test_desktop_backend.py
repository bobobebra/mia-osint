import json

from mia import __version__
from mia.desktop_backend import _self_test
from mia.registry import PluginRegistry


def test_self_test_discovers_packaged_plugins(tmp_path) -> None:
    result_path = tmp_path / "self-test.json"

    assert _self_test(result_path) == 0

    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["status"] == "ok"
    assert result["version"] == __version__
    assert result["plugin_count"] == len(result["plugins"])
    assert "maigret" in result["plugins"]


def test_self_test_reports_plugin_discovery_failure(tmp_path, monkeypatch) -> None:
    result_path = tmp_path / "self-test.json"

    def fail_discovery(cls):
        raise ModuleNotFoundError("No module named 'mia.plugins'")

    monkeypatch.setattr(PluginRegistry, "discover", classmethod(fail_discovery))

    assert _self_test(result_path) == 1

    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result == {
        "status": "error",
        "version": __version__,
        "error": "No module named 'mia.plugins'",
    }
