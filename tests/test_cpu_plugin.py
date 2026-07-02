from unittest.mock import patch

from doctor.models import Status
from doctor.plugins.cpu import CPUPlugin

PATCH_TARGET = "doctor.services.process_service.ProcessService.sample_system_and_processes"


def test_cpu_plugin_passes_under_normal_load():
    plugin = CPUPlugin()
    with patch(PATCH_TARGET, return_value=([], 10.0, (1.0, 1.0, 1.0))):
        result = plugin.run()

    assert result.status == Status.PASS
    assert result.score_delta == 0


def test_cpu_plugin_warns_on_high_usage():
    plugin = CPUPlugin()
    with patch(PATCH_TARGET, return_value=([], 75.0, (2.0, 2.0, 2.0))):
        result = plugin.run()

    assert result.status == Status.WARN
    assert result.score_delta == 5


def test_cpu_plugin_fails_on_critical_usage():
    plugin = CPUPlugin()
    with patch(PATCH_TARGET, return_value=([], 95.0, (4.0, 4.0, 4.0))):
        result = plugin.run()

    assert result.status == Status.FAIL
    assert result.score_delta == 15


def test_cpu_plugin_flags_runaway_process():
    plugin = CPUPlugin()
    with patch(
        PATCH_TARGET,
        return_value=([("Antigravity IDE Helper", 85.0)], 30.0, (1.0, 1.0, 1.0)),
    ):
        result = plugin.run()

    assert result.status == Status.WARN
    assert len(result.recommendations) == 1
    assert "Antigravity IDE Helper" in result.recommendations[0]


def test_cpu_plugin_never_raises_on_unexpected_failure():
    plugin = CPUPlugin()
    with patch(PATCH_TARGET, side_effect=RuntimeError("boom")):
        result = plugin.run()

    assert result.status == Status.FAIL
    assert "Could not read CPU information" in result.findings[0].summary