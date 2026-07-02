from unittest.mock import MagicMock, patch

from doctor.models import Status
from doctor.plugins.disk import DiskPlugin


def _mock_usage(percent: float, used_gb: float, total_gb: float) -> MagicMock:
    usage = MagicMock()
    usage.percent = percent
    usage.used = used_gb * (1024**3)
    usage.total = total_gb * (1024**3)
    usage.free = (total_gb - used_gb) * (1024**3)
    return usage


def test_disk_plugin_passes_under_normal_usage():
    plugin = DiskPlugin()
    with patch("psutil.disk_usage", return_value=_mock_usage(50.0, 250.0, 500.0)):
        result = plugin.run()

    assert result.status == Status.PASS
    assert result.score_delta == 0


def test_disk_plugin_warns_when_getting_full():
    plugin = DiskPlugin()
    with patch("psutil.disk_usage", return_value=_mock_usage(88.0, 440.0, 500.0)):
        result = plugin.run()

    assert result.status == Status.WARN
    assert result.score_delta == 5


def test_disk_plugin_fails_when_nearly_full():
    plugin = DiskPlugin()
    with patch("psutil.disk_usage", return_value=_mock_usage(97.0, 485.0, 500.0)):
        result = plugin.run()

    assert result.status == Status.FAIL
    assert result.score_delta == 15


def test_disk_plugin_never_raises_on_psutil_failure():
    plugin = DiskPlugin()
    with patch("psutil.disk_usage", side_effect=RuntimeError("boom")):
        result = plugin.run()

    assert result.status == Status.FAIL
    assert "Could not read disk information" in result.findings[0].summary