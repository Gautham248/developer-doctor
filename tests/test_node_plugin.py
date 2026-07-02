from unittest.mock import patch

from doctor.models import Status
from doctor.plugins.node import NodePlugin


def test_node_plugin_not_supported_without_binary():
    plugin = NodePlugin()
    with patch("shutil.which", return_value=None):
        assert plugin.is_supported() is False


def test_detect_version_manager_mise():
    plugin = NodePlugin()
    path = "/Users/dev/.local/share/mise/installs/node/22.0.0/bin/node"
    assert plugin._detect_version_manager(path) == "mise"


def test_detect_version_manager_nvm():
    plugin = NodePlugin()
    path = "/Users/dev/.nvm/versions/node/v20.0.0/bin/node"
    assert plugin._detect_version_manager(path) == "nvm"


def test_detect_version_manager_unknown_without_path():
    plugin = NodePlugin()
    assert plugin._detect_version_manager(None) == "unknown"


def test_node_plugin_passes_with_single_manager():
    plugin = NodePlugin()
    with (
        patch("shutil.which", return_value="/Users/dev/.local/share/mise/installs/node/22.0.0/bin/node"),
        patch.object(plugin, "_node_version", return_value="22.0.0"),
        patch.object(plugin, "_detect_package_manager", return_value="pnpm"),
        patch.object(plugin, "_detect_conflicting_managers", return_value=["mise"]),
    ):
        result = plugin.run()

    assert result.status == Status.PASS
    assert result.score_delta == 0


def test_node_plugin_warns_on_multiple_managers():
    plugin = NodePlugin()
    with (
        patch("shutil.which", return_value="/Users/dev/.nvm/versions/node/v20.0.0/bin/node"),
        patch.object(plugin, "_node_version", return_value="20.0.0"),
        patch.object(plugin, "_detect_package_manager", return_value="npm"),
        patch.object(plugin, "_detect_conflicting_managers", return_value=["nvm", "mise"]),
    ):
        result = plugin.run()

    assert result.status == Status.WARN
    assert result.score_delta == 5
    assert any("Multiple Node version managers" in f.summary for f in result.findings)


def test_node_plugin_never_raises_on_unexpected_failure():
    plugin = NodePlugin()
    with patch("shutil.which", side_effect=RuntimeError("boom")):
        result = plugin.run()

    assert result.status == Status.FAIL
    assert "Could not run Node diagnostics" in result.findings[0].summary