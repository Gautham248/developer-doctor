import pytest

from doctor.models import Finding, PluginResult, Status
from doctor.plugins.base import DoctorPlugin
from doctor.sdk.testing import PluginTestHarness


class _FakePlugin(DoctorPlugin):
    name = "fake"
    description = "fake"

    def run(self) -> PluginResult:
        return PluginResult(plugin_name=self.name, status=Status.PASS, findings=[Finding(summary="ok")])


class _RaisingPlugin(DoctorPlugin):
    name = "raising"
    description = "fake"

    def run(self) -> PluginResult:
        raise RuntimeError("boom")


def test_harness_run_returns_plugin_result():
    harness = PluginTestHarness()
    result = harness.run(_FakePlugin())
    assert result.status == Status.PASS


def test_harness_run_propagates_exceptions_from_broken_plugin():
    harness = PluginTestHarness()
    with pytest.raises(RuntimeError):
        harness.run(_RaisingPlugin())


def test_harness_check_is_supported_default_true():
    harness = PluginTestHarness()
    assert harness.check_is_supported(_FakePlugin()) is True