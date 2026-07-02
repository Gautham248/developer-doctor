from abc import ABC, abstractmethod

from doctor.models import PluginResult


class DoctorPlugin(ABC):
    """Base class every diagnostic plugin must implement.

    Per the plugin-first architecture, this is the ONLY contract the core
    knows about. The core has zero knowledge of what any given plugin
    actually checks.
    """

    name: str
    description: str

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