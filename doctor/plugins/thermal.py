"""Thermal plugin — reports system thermal pressure in the standard doctor report.

Integrates alongside CPUPlugin to give a thermal health verdict. On macOS it
reports the thermal pressure level (Nominal/Fair/Serious/Critical) plus power
consumption in mW. On Linux it reports actual temperature in °C.

When the system is Serious or Critical, recommendations name the top offending
processes and point the user to `doctor thermal --optimize`.
"""

from __future__ import annotations

from doctor.capabilities import Capability
from doctor.models import Finding, PluginResult, Status
from doctor.plugins.base import DoctorPlugin
from doctor.services.thermal_service import (
    ThermalService,
    LEVEL_NOMINAL,
    LEVEL_FAIR,
    LEVEL_SERIOUS,
    LEVEL_CRITICAL,
)

DEFAULT_THRESHOLDS = {
    # Linux temperature thresholds (°C)
    "linux_warn_temp_c": 60.0,
    "linux_fail_temp_c": 80.0,
    # Per-process CPU% to mention in recommendations
    "warn_cpu_percent": 40.0,
}

LEVEL_TO_STATUS = {
    LEVEL_NOMINAL: (Status.PASS, 0),
    LEVEL_FAIR: (Status.WARN, 5),
    LEVEL_SERIOUS: (Status.FAIL, 15),
    LEVEL_CRITICAL: (Status.FAIL, 20),
}


class ThermalPlugin(DoctorPlugin):
    name = "thermal"
    description = "Reports system thermal pressure and heat-generating processes."
    capabilities = [Capability.THERMAL_MONITORING]

    def __init__(self, thresholds: dict[str, float] | None = None) -> None:
        self.thresholds = {**DEFAULT_THRESHOLDS, **(thresholds or {})}

    def run(self) -> PluginResult:
        try:
            service = self.use_service(ThermalService)
            state = service.get_thermal_state()
            processes = service.get_thermal_processes(limit=3)

            # --- Determine status and score delta ---
            level = state.level
            status, score_delta = LEVEL_TO_STATUS.get(level, (Status.INFO, 0))

            # Override with temperature-based thresholds on Linux
            if state.temperature_c is not None:
                if state.temperature_c >= self.thresholds["linux_fail_temp_c"]:
                    status = Status.FAIL
                    score_delta = max(score_delta, 15)
                elif state.temperature_c >= self.thresholds["linux_warn_temp_c"]:
                    if status == Status.PASS:
                        status = Status.WARN
                        score_delta = max(score_delta, 5)

            # --- Build findings ---
            level_label = level.capitalize()
            findings: list[Finding] = []

            if state.temperature_c is not None:
                findings.append(
                    Finding(
                        summary=f"Thermal pressure: {level_label} "
                                f"({state.temperature_c:.1f} °C)",
                    )
                )
            else:
                findings.append(Finding(summary=f"Thermal pressure: {level_label}"))

            if state.cpu_power_mw is not None:
                power_parts = [f"CPU {state.cpu_power_mw:.0f} mW"]
                if state.gpu_power_mw is not None:
                    power_parts.append(f"GPU {state.gpu_power_mw:.0f} mW")
                if state.ane_power_mw is not None:
                    power_parts.append(f"ANE {state.ane_power_mw:.0f} mW")
                findings.append(Finding(summary="Power: " + "  |  ".join(power_parts)))

            for proc in processes:
                findings.append(
                    Finding(summary=f"{proc.name}: {proc.cpu_percent:.0f}% CPU")
                )

            # --- Build recommendations ---
            recommendations: list[str] = []

            if status in (Status.WARN, Status.FAIL):
                hot_procs = [
                    p for p in processes
                    if p.cpu_percent >= self.thresholds["warn_cpu_percent"]
                ]
                if hot_procs:
                    names = ", ".join(f"'{p.name}'" for p in hot_procs[:3])
                    recommendations.append(
                        f"High-heat processes detected: {names}. "
                        f"Run `doctor thermal --optimize` to reduce pressure."
                    )
                else:
                    recommendations.append(
                        "Thermal pressure is elevated. "
                        "Run `doctor thermal --optimize` to identify and close "
                        "non-essential processes."
                    )

            if state.pmset_warnings:
                recommendations.append(
                    "pmset reports thermal/performance warnings — "
                    "the system has been throttling recently."
                )

            return PluginResult(
                plugin_name=self.name,
                status=status,
                score_delta=score_delta,
                findings=findings,
                recommendations=recommendations,
                metadata={
                    "thermal_level": level,
                    "temperature_c": state.temperature_c,
                    "cpu_power_mw": state.cpu_power_mw,
                    "gpu_power_mw": state.gpu_power_mw,
                    "ane_power_mw": state.ane_power_mw,
                    "source": state.source,
                    "pmset_warnings": state.pmset_warnings,
                },
            )
        except Exception as e:
            return PluginResult(
                plugin_name=self.name,
                status=Status.FAIL,
                findings=[
                    Finding(
                        summary="Could not read thermal information",
                        detail=str(e),
                    )
                ],
            )
