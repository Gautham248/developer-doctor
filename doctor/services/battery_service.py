import platform
import re
import subprocess
from typing import Any

from doctor.capabilities import Capability
from doctor.services.base import BaseService


class BatteryService(BaseService):
    """Shared, testable interface to battery charge/health/cycle data."""

    required_capability = Capability.BATTERY_INFORMATION

    def get_battery_status(self) -> Any:
        """Return psutil's sensors_battery() result, or None on any failure.

        Typed as Any rather than a private psutil internal type — the
        stub type isn't publicly exported, and Any keeps this honest
        rather than reaching into psutil internals for a type hint.
        """
        try:
            import psutil

            return psutil.sensors_battery()
        except Exception:
            return None

    def get_macos_health(self) -> tuple[int, float] | None:
        """Read cycle count and max-capacity health via system_profiler.

        macOS-only: psutil doesn't expose this data on any platform, and
        there's no equivalent Linux/Windows API being handled yet.
        Returns None outside macOS or if parsing ever fails.
        """
        if platform.system() != "Darwin":
            return None

        try:
            output = subprocess.run(
                ["system_profiler", "SPPowerDataType"],
                capture_output=True,
                text=True,
                timeout=5,
                check=True,
            ).stdout

            cycle_match = re.search(r"Cycle Count:\s*(\d+)", output)
            max_cap_match = re.search(r"Maximum Capacity:\s*(\d+)%", output)

            if cycle_match and max_cap_match:
                return int(cycle_match.group(1)), float(max_cap_match.group(1))
            return None
        except (subprocess.SubprocessError, OSError, ValueError):
            return None