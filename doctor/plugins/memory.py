import psutil

from doctor.models import Finding, PluginResult, Status
from doctor.plugins.base import DoctorPlugin

# Defaults — overridable per-project via doctor.toml:
# [thresholds.memory]
# warn_percent = 75
# fail_percent = 92
# warn_swap_gb = 1.5
# fail_swap_gb = 6
DEFAULT_THRESHOLDS = {
    "warn_percent": 80.0,
    "fail_percent": 95.0,
    "warn_swap_gb": 2.0,
    "fail_swap_gb": 8.0,
}

WARN_SCORE_DELTA = 5
FAIL_SCORE_DELTA = 15


class MemoryPlugin(DoctorPlugin):
    name = "memory"
    description = "Reports RAM and swap usage, flags memory pressure."

    def __init__(self, thresholds: dict[str, float] | None = None) -> None:
        self.thresholds = {**DEFAULT_THRESHOLDS, **(thresholds or {})}

    def run(self) -> PluginResult:
        try:
            vm = psutil.virtual_memory()
            swap = psutil.swap_memory()

            used_gb = round(vm.used / (1024**3), 1)
            total_gb = round(vm.total / (1024**3), 1)
            swap_used_gb = round(swap.used / (1024**3), 1)

            findings = [
                Finding(summary=f"RAM: {used_gb} GB / {total_gb} GB ({vm.percent:.0f}%)"),
            ]
            recommendations: list[str] = []
            status = Status.PASS
            score_delta = 0

            if vm.percent >= self.thresholds["fail_percent"]:
                status = Status.FAIL
                score_delta = FAIL_SCORE_DELTA
                recommendations.append(
                    "Memory usage is critically high. Close unused applications "
                    "or browser tabs to free up RAM."
                )
            elif vm.percent >= self.thresholds["warn_percent"]:
                status = Status.WARN
                score_delta = WARN_SCORE_DELTA
                recommendations.append(
                    "Memory usage is elevated. Consider closing memory-heavy apps."
                )

            if swap_used_gb > 0:
                findings.append(Finding(summary=f"Swap: {swap_used_gb} GB used"))

                if swap_used_gb >= self.thresholds["fail_swap_gb"]:
                    status = Status.FAIL
                    score_delta = max(score_delta, FAIL_SCORE_DELTA)
                    recommendations.append(
                        f"Heavy swap usage ({swap_used_gb} GB) indicates severe memory "
                        f"pressure — the system is actively paging to disk, which will "
                        f"feel slow. Restart memory-heavy applications."
                    )
                elif swap_used_gb >= self.thresholds["warn_swap_gb"]:
                    if status == Status.PASS:
                        status = Status.WARN
                    score_delta = max(score_delta, WARN_SCORE_DELTA)
                    recommendations.append(
                        f"Some swap is in use ({swap_used_gb} GB), which can slow things "
                        f"down. Keep an eye on memory usage if things feel sluggish."
                    )

            return PluginResult(
                plugin_name=self.name,
                status=status,
                score_delta=score_delta,
                findings=findings,
                recommendations=recommendations,
                metadata={
                    "ram_used_gb": used_gb,
                    "ram_total_gb": total_gb,
                    "ram_percent": vm.percent,
                    "swap_used_gb": swap_used_gb,
                },
            )
        except Exception as e:
            return PluginResult(
                plugin_name=self.name,
                status=Status.FAIL,
                findings=[Finding(summary="Could not read memory information", detail=str(e))],
            )