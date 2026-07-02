from unittest.mock import MagicMock, patch

from doctor.services.battery_service import BatteryService


def test_get_battery_status_returns_psutil_result():
    fake_battery = MagicMock(percent=80.0, power_plugged=True)
    service = BatteryService()
    with patch("psutil.sensors_battery", return_value=fake_battery):
        assert service.get_battery_status() is fake_battery


def test_get_battery_status_returns_none_on_exception():
    service = BatteryService()
    with patch("psutil.sensors_battery", side_effect=RuntimeError("boom")):
        assert service.get_battery_status() is None


def test_get_macos_health_returns_none_off_darwin():
    service = BatteryService()
    with patch("platform.system", return_value="Linux"):
        assert service.get_macos_health() is None


def test_get_macos_health_parses_output_on_darwin():
    service = BatteryService()
    mock_result = MagicMock(stdout="Cycle Count: 42\nMaximum Capacity: 93%\n")
    with (
        patch("platform.system", return_value="Darwin"),
        patch("subprocess.run", return_value=mock_result),
    ):
        assert service.get_macos_health() == (42, 93.0)


def test_get_macos_health_returns_none_on_parse_failure():
    service = BatteryService()
    mock_result = MagicMock(stdout="no useful data here")
    with (
        patch("platform.system", return_value="Darwin"),
        patch("subprocess.run", return_value=mock_result),
    ):
        assert service.get_macos_health() is None