import psutil

from doctor.models import Finding, PluginResult, Status
from doctor.plugins.base import DoctorPlugin
from doctor.capabilities import Capability

# Defaults — overridable per-project via doctor.toml:
# [thresholds.disk]
# warn_percent = 80
# fail_percent = 92
DEFAULT_THRESHOLDS = {
    "warn_percent": 85.0,
    "fail_percent": 95.0,
}

WARN_SCORE_DELTA = 5
FAIL_SCORE_DELTA = 15


class DiskPlugin(DoctorPlugin):
    name = "disk"
    description = "Reports disk capacity for the primary volume."
    capabilities: list[Capability] = []
    def __init__(self, thresholds: dict[str, float] | None = None) -> None:
        self.thresholds = {**DEFAULT_THRESHOLDS, **(thresholds or {})}

    def run(self) -> PluginResult:
        try:
            usage = psutil.disk_usage("/")

            used_gb = round(usage.used / (1024**3), 1)
            total_gb = round(usage.total / (1024**3), 1)
            free_gb = round(usage.free / (1024**3), 1)

            findings = [
                Finding(
                    summary=f"Disk: {used_gb} GB / {total_gb} GB used ({usage.percent:.0f}%)"
                ),
                Finding(summary=f"{free_gb} GB free"),
            ]
            recommendations: list[str] = []
            status = Status.PASS
            score_delta = 0

            if usage.percent >= self.thresholds["fail_percent"]:
                status = Status.FAIL
                score_delta = FAIL_SCORE_DELTA
                recommendations.append(
                    f"Disk is critically full ({usage.percent:.0f}% used, only "
                    f"{free_gb} GB free). Free up space soon — builds, package "
                    f"managers, and even the OS itself can start failing near capacity."
                )
            elif usage.percent >= self.thresholds["warn_percent"]:
                status = Status.WARN
                score_delta = WARN_SCORE_DELTA
                recommendations.append(
                    f"Disk usage is getting high ({usage.percent:.0f}% used). "
                    f"Consider clearing out large files, caches, or old Docker images."
                )

            return PluginResult(
                plugin_name=self.name,
                status=status,
                score_delta=score_delta,
                findings=findings,
                recommendations=recommendations,
                metadata={
                    "used_gb": used_gb,
                    "total_gb": total_gb,
                    "free_gb": free_gb,
                    "percent": usage.percent,
                },
            )
        except Exception as e:
            return PluginResult(
                plugin_name=self.name,
                status=Status.FAIL,
                findings=[Finding(summary="Could not read disk information", detail=str(e))],
            )