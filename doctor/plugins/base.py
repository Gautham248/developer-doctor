from abc import ABC, abstractmethod
from typing import TypeVar

from doctor.capabilities import Capability, CapabilityError
from doctor.models import PluginResult
from doctor.services.base import BaseService

ServiceT = TypeVar("ServiceT", bound=BaseService)


class DoctorPlugin(ABC):
    """Base class every diagnostic plugin must implement.

    Per the plugin-first architecture, this is the ONLY contract the core
    knows about. The core has zero knowledge of what any given plugin
    actually checks.
    """

    name: str
    description: str
    capabilities: list[Capability] = []

    def is_supported(self) -> bool:
        """Return False to skip this plugin on the current platform.

        Default: supported everywhere. Override for platform-specific
        plugins (e.g. Homebrew is macOS/Linux only).
        """
        return True

    @abstractmethod
    def run(self) -> PluginResult:
        """Execute the diagnostic and return a structured result.

        Must never raise. Plugins are responsible for catching their own
        exceptions and returning a FAIL/INFO PluginResult instead — a
        misbehaving plugin must never crash the doctor process.
        """
        ...

    def use_service(self, service_class: type[ServiceT]) -> ServiceT:
        """Return an instance of a shared service (§12), enforcing that
        this plugin declared the capability (§11) that service requires.

        Raises CapabilityError if the capability wasn't declared — an
        undeclared capability is treated as a bug in the plugin, not
        something to silently allow.
        """
        required = service_class.required_capability
        if required not in self.capabilities:
            raise CapabilityError(
                f"{type(self).__name__} attempted to use "
                f"{service_class.__name__}, which requires capability "
                f"'{required.value}', but did not declare it in "
                f"`capabilities`."
            )
        return service_class()