import psutil

from doctor.models import Finding, PluginResult, Status
from doctor.plugins.base import DoctorPlugin

# Hardcoded thresholds — to be made configurable via doctor.toml (§15) later.
WARN_MEMORY_PERCENT = 80.0
FAIL_MEMORY_PERCENT = 95.0
WARN_SWAP_USED_GB = 2.0
FAIL_SWAP_USED_GB = 8.0

WARN_SCORE_DELTA = 5
FAIL_SCORE_DELTA = 15


class MemoryPlugin(DoctorPlugin):
    name = "memory"
    description = "Reports RAM and swap usage, flags memory pressure."

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

            if vm.percent >= FAIL_MEMORY_PERCENT:
                status = Status.FAIL
                score_delta = FAIL_SCORE_DELTA
                recommendations.append(
                    "Memory usage is critically high. Close unused applications "
                    "or browser tabs to free up RAM."
                )
            elif vm.percent >= WARN_MEMORY_PERCENT:
                status = Status.WARN
                score_delta = WARN_SCORE_DELTA
                recommendations.append(
                    "Memory usage is elevated. Consider closing memory-heavy apps."
                )

            if swap_used_gb > 0:
                findings.append(Finding(summary=f"Swap: {swap_used_gb} GB used"))

                if swap_used_gb >= FAIL_SWAP_USED_GB:
                    status = Status.FAIL
                    score_delta = max(score_delta, FAIL_SCORE_DELTA)
                    recommendations.append(
                        f"Heavy swap usage ({swap_used_gb} GB) indicates severe memory "
                        f"pressure — the system is actively paging to disk, which will "
                        f"feel slow. Restart memory-heavy applications."
                    )
                elif swap_used_gb >= WARN_SWAP_USED_GB:
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