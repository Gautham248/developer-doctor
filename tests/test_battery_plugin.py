from unittest.mock import MagicMock, patch

from doctor.models import Status
from doctor.plugins.battery import BatteryPlugin


def _mock_battery(percent: float, plugged: bool) -> MagicMock:
    battery = MagicMock()
    battery.percent = percent
    battery.power_plugged = plugged
    return battery


def test_battery_plugin_not_supported_without_battery():
    plugin = BatteryPlugin()
    with patch("psutil.sensors_battery", return_value=None):
        assert plugin.is_supported() is False


def test_battery_plugin_passes_on_healthy_battery():
    plugin = BatteryPlugin()
    with (
        patch("psutil.sensors_battery", return_value=_mock_battery(80.0, True)),
        patch.object(plugin, "_read_macos_health", return_value=(200, 95.0)),
    ):
        result = plugin.run()

    assert result.status == Status.PASS
    assert result.score_delta == 0


def test_battery_plugin_warns_on_degraded_health():
    plugin = BatteryPlugin()
    with (
        patch("psutil.sensors_battery", return_value=_mock_battery(60.0, False)),
        patch.object(plugin, "_read_macos_health", return_value=(850, 78.0)),
    ):
        result = plugin.run()

    assert result.status == Status.WARN
    assert result.score_delta == 5


def test_battery_plugin_fails_on_critical_health():
    plugin = BatteryPlugin()
    with (
        patch("psutil.sensors_battery", return_value=_mock_battery(45.0, False)),
        patch.object(plugin, "_read_macos_health", return_value=(1200, 55.0)),
    ):
        result = plugin.run()

    assert result.status == Status.FAIL
    assert result.score_delta == 15


def test_battery_plugin_works_without_health_data():
    """Non-macOS or parse-failure case: charge/plugged still reported, no crash."""
    plugin = BatteryPlugin()
    with (
        patch("psutil.sensors_battery", return_value=_mock_battery(70.0, True)),
        patch.object(plugin, "_read_macos_health", return_value=None),
    ):
        result = plugin.run()

    assert result.status == Status.PASS
    assert result.metadata["cycle_count"] is None


def test_battery_plugin_never_raises_on_psutil_failure():
    plugin = BatteryPlugin()
    with patch("psutil.sensors_battery", side_effect=RuntimeError("boom")):
        result = plugin.run()

    assert result.status == Status.FAIL
    assert "Could not read battery information" in result.findings[0].summary