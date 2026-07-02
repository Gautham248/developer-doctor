import pytest

from doctor.capabilities import Capability, CapabilityError
from doctor.plugins.base import DoctorPlugin
from doctor.services.base import BaseService


class FakeService(BaseService):
    required_capability = Capability.PROCESS_INSPECTION


class PluginWithCapability(DoctorPlugin):
    name = "fake_with_cap"
    description = "fake"
    capabilities = [Capability.PROCESS_INSPECTION]

    def run(self):
        raise NotImplementedError


class PluginWithoutCapability(DoctorPlugin):
    name = "fake_without_cap"
    description = "fake"
    capabilities = []

    def run(self):
        raise NotImplementedError


def test_use_service_succeeds_when_capability_declared():
    plugin = PluginWithCapability()
    service = plugin.use_service(FakeService)
    assert isinstance(service, FakeService)


def test_use_service_raises_when_capability_not_declared():
    plugin = PluginWithoutCapability()
    with pytest.raises(CapabilityError):
        plugin.use_service(FakeService)