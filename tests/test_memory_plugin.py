from unittest.mock import MagicMock, patch

from doctor.models import Status
from doctor.plugins.memory import MemoryPlugin


def _mock_vm(percent: float, used_gb: float, total_gb: float) -> MagicMock:
    vm = MagicMock()
    vm.percent = percent
    vm.used = used_gb * (1024**3)
    vm.total = total_gb * (1024**3)
    return vm


def _mock_swap(used_gb: float) -> MagicMock:
    swap = MagicMock()
    swap.used = used_gb * (1024**3)
    return swap


def test_memory_plugin_passes_under_normal_usage():
    plugin = MemoryPlugin()
    with (
        patch("psutil.virtual_memory", return_value=_mock_vm(50.0, 8.0, 16.0)),
        patch("psutil.swap_memory", return_value=_mock_swap(0.0)),
    ):
        result = plugin.run()

    assert result.status == Status.PASS
    assert result.score_delta == 0


def test_memory_plugin_warns_on_high_ram():
    plugin = MemoryPlugin()
    with (
        patch("psutil.virtual_memory", return_value=_mock_vm(85.0, 13.6, 16.0)),
        patch("psutil.swap_memory", return_value=_mock_swap(0.0)),
    ):
        result = plugin.run()

    assert result.status == Status.WARN
    assert result.score_delta == 5


def test_memory_plugin_fails_on_critical_ram():
    plugin = MemoryPlugin()
    with (
        patch("psutil.virtual_memory", return_value=_mock_vm(97.0, 15.5, 16.0)),
        patch("psutil.swap_memory", return_value=_mock_swap(0.0)),
    ):
        result = plugin.run()

    assert result.status == Status.FAIL
    assert result.score_delta == 15


def test_memory_plugin_fails_on_heavy_swap():
    plugin = MemoryPlugin()
    with (
        patch("psutil.virtual_memory", return_value=_mock_vm(60.0, 9.6, 16.0)),
        patch("psutil.swap_memory", return_value=_mock_swap(9.0)),
    ):
        result = plugin.run()

    assert result.status == Status.FAIL
    assert result.score_delta == 15
    assert any("swap" in rec.lower() for rec in result.recommendations)


def test_memory_plugin_never_raises_on_psutil_failure():
    plugin = MemoryPlugin()
    with patch("psutil.virtual_memory", side_effect=RuntimeError("boom")):
        result = plugin.run()

    assert result.status == Status.FAIL
    assert "Could not read memory information" in result.findings[0].summary