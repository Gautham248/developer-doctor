import platform
import re
import subprocess

import psutil

from doctor.models import Finding, PluginResult, Status
from doctor.plugins.base import DoctorPlugin
from doctor.capabilities import Capability
# Defaults — overridable per-project via doctor.toml:
# [thresholds.battery]
# warn_health_percent = 75
# fail_health_percent = 55
# warn_cycle_count = 700
# fail_cycle_count = 900
DEFAULT_THRESHOLDS = {
    "warn_health_percent": 80.0,
    "fail_health_percent": 60.0,
    "warn_cycle_count": 800.0,
    "fail_cycle_count": 1000.0,
}

WARN_SCORE_DELTA = 5
FAIL_SCORE_DELTA = 15


class BatteryPlugin(DoctorPlugin):
    name = "battery"
    description = "Reports battery health, cycle count, and charging state."
    capabilities = [Capability.BATTERY_INFORMATION, Capability.SHELL_COMMANDS]

    def __init__(self, thresholds: dict[str, float] | None = None) -> None:
        self.thresholds = {**DEFAULT_THRESHOLDS, **(thresholds or {})}

    def is_supported(self) -> bool:
        """Only run on systems that report a battery (i.e. not desktops)."""
        try:
            return psutil.sensors_battery() is not None
        except Exception:
            return False

    def run(self) -> PluginResult:
        try:
            battery = psutil.sensors_battery()
            if battery is None:
                return PluginResult(
                    plugin_name=self.name,
                    status=Status.INFO,
                    findings=[Finding(summary="No battery detected")],
                )

            findings = [
                Finding(summary=f"Charge: {battery.percent:.0f}%"),
                Finding(summary="Plugged in" if battery.power_plugged else "On battery power"),
            ]
            recommendations: list[str] = []
            status = Status.PASS
            score_delta = 0

            health_data = self._read_macos_health()
            cycle_count = health_data[0] if health_data else None
            max_capacity_percent = health_data[1] if health_data else None

            if health_data is not None:
                findings.append(Finding(summary=f"Cycle count: {cycle_count}"))
                findings.append(
                    Finding(summary=f"Battery health: {max_capacity_percent:.0f}% of design capacity")
                )

                critical = (
                    max_capacity_percent is not None
                    and max_capacity_percent <= self.thresholds["fail_health_percent"]
                ) or (
                    cycle_count is not None and cycle_count >= self.thresholds["fail_cycle_count"]
                )
                degraded = (
                    max_capacity_percent is not None
                    and max_capacity_percent <= self.thresholds["warn_health_percent"]
                ) or (
                    cycle_count is not None and cycle_count >= self.thresholds["warn_cycle_count"]
                )

                if critical:
                    status = Status.FAIL
                    score_delta = FAIL_SCORE_DELTA
                    recommendations.append(
                        "Battery health is significantly degraded. If unplugged runtime "
                        "matters for your workflow, consider a battery service appointment."
                    )
                elif degraded:
                    status = Status.WARN
                    score_delta = WARN_SCORE_DELTA
                    recommendations.append(
                        "Battery health is starting to degrade. Not urgent, but worth "
                        "keeping an eye on if runtime feels shorter than it used to."
                    )

            return PluginResult(
                plugin_name=self.name,
                status=status,
                score_delta=score_delta,
                findings=findings,
                recommendations=recommendations,
                metadata={
                    "charge_percent": battery.percent,
                    "power_plugged": battery.power_plugged,
                    "cycle_count": cycle_count,
                    "max_capacity_percent": max_capacity_percent,
                },
            )
        except Exception as e:
            return PluginResult(
                plugin_name=self.name,
                status=Status.FAIL,
                findings=[Finding(summary="Could not read battery information", detail=str(e))],
            )

    def _read_macos_health(self) -> tuple[int, float] | None:
        """Read cycle count and max-capacity health via system_profiler.

        macOS-only: psutil doesn't expose this data on any platform, and
        there's no equivalent Linux/Windows API being handled yet. Returns
        None outside macOS or if parsing ever fails — the plugin degrades
        gracefully to charge %/plugged-state only in that case, it never
        raises up to run().
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