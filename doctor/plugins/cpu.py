from doctor.capabilities import Capability
from doctor.models import Finding, PluginResult, Status
from doctor.plugins.base import DoctorPlugin
from doctor.services.process_service import ProcessService

# Defaults — overridable per-project via doctor.toml:
# [thresholds.cpu]
# warn_percent = 60
# fail_percent = 85
# runaway_process_percent = 75
DEFAULT_THRESHOLDS = {
    "warn_percent": 70.0,
    "fail_percent": 90.0,
    "runaway_process_percent": 80.0,
}

WARN_SCORE_DELTA = 5
FAIL_SCORE_DELTA = 15


class CPUPlugin(DoctorPlugin):
    name = "cpu"
    description = "Reports CPU usage and flags runaway processes."
    capabilities = [Capability.PROCESS_INSPECTION]

    def __init__(self, thresholds: dict[str, float] | None = None) -> None:
        self.thresholds = {**DEFAULT_THRESHOLDS, **(thresholds or {})}

    def run(self) -> PluginResult:
        try:
            process_service = self.use_service(ProcessService)
            top_processes, cpu_percent, load_avg = process_service.sample_system_and_processes(
                limit=3
            )

            findings = [Finding(summary=f"CPU usage: {cpu_percent:.0f}%")]
            recommendations: list[str] = []
            status = Status.PASS
            score_delta = 0

            if cpu_percent >= self.thresholds["fail_percent"]:
                status = Status.FAIL
                score_delta = FAIL_SCORE_DELTA
            elif cpu_percent >= self.thresholds["warn_percent"]:
                status = Status.WARN
                score_delta = WARN_SCORE_DELTA

            for proc_name, proc_cpu in top_processes:
                findings.append(Finding(summary=f"{proc_name}: {proc_cpu:.0f}% CPU"))
                if proc_cpu >= self.thresholds["runaway_process_percent"]:
                    if status == Status.PASS:
                        status = Status.WARN
                        score_delta = max(score_delta, WARN_SCORE_DELTA)
                    recommendations.append(
                        f"'{proc_name}' has been using {proc_cpu:.0f}% CPU. "
                        f"Run `doctor thermal --optimize` to review it and close "
                        f"it safely if it's not doing legitimate work."
                    )

            if status != Status.PASS and not recommendations:
                recommendations.append(
                    "Overall CPU usage is high. Run `doctor thermal --optimize` "
                    "to scan running processes and get a safe plan to reduce it."
                )

            return PluginResult(
                plugin_name=self.name,
                status=status,
                score_delta=score_delta,
                findings=findings,
                recommendations=recommendations,
                metadata={
                    "cpu_percent": cpu_percent,
                    "load_avg_1min": load_avg[0],
                    "load_avg_5min": load_avg[1],
                    "load_avg_15min": load_avg[2],
                },
            )
        except Exception as e:
            return PluginResult(
                plugin_name=self.name,
                status=Status.FAIL,
                findings=[Finding(summary="Could not read CPU information", detail=str(e))],
            )