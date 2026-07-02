from doctor.models import Status
from doctor.plugins.system import SystemPlugin


def test_system_plugin_runs_and_returns_info_status():
    plugin = SystemPlugin()
    result = plugin.run()

    assert result.plugin_name == "system"
    assert result.status == Status.INFO
    assert len(result.findings) == 3


def test_system_plugin_metadata_contains_expected_keys():
    plugin = SystemPlugin()
    result = plugin.run()

    assert "os" in result.metadata
    assert "architecture" in result.metadata
    assert "total_ram_gb" in result.metadata
    assert "uptime_hours" in result.metadata
    assert result.metadata["total_ram_gb"] > 0


def test_system_plugin_is_supported_on_all_platforms():
    plugin = SystemPlugin()
    assert plugin.is_supported() is True