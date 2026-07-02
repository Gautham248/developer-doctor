import time

import psutil

from doctor.models import Finding, PluginResult, Status
from doctor.plugins.base import DoctorPlugin

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

SAMPLE_INTERVAL_SECONDS = 0.5


class CPUPlugin(DoctorPlugin):
    name = "cpu"
    description = "Reports CPU usage and flags runaway processes."

    def __init__(self, thresholds: dict[str, float] | None = None) -> None:
        self.thresholds = {**DEFAULT_THRESHOLDS, **(thresholds or {})}

    def run(self) -> PluginResult:
        try:
            top_processes, cpu_percent, load_avg = self._sample()

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
                        f"If this persists, consider restarting it."
                    )

            if status != Status.PASS and not recommendations:
                recommendations.append(
                    "Overall CPU usage is high. Check the top processes above "
                    "to identify what's consuming resources."
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

    def _sample(self) -> tuple[list[tuple[str, float]], float, tuple[float, float, float]]:
        """Prime and sample CPU usage for both the system and individual processes.

        psutil's cpu_percent() returns 0.0 (or garbage) on the very first
        call for any given process/handle, since it needs a baseline to
        diff against. We prime everything with a non-blocking call first,
        sleep once, then take the real reading — one shared sample window
        for both the system-wide and per-process numbers, so we only pay
        the latency cost once.
        """
        psutil.cpu_percent(interval=None)
        procs = []
        for proc in psutil.process_iter(["name"]):
            try:
                proc.cpu_percent(interval=None)
                procs.append(proc)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        time.sleep(SAMPLE_INTERVAL_SECONDS)

        cpu_percent = psutil.cpu_percent(interval=None)
        load_avg = psutil.getloadavg()

        results = []
        for proc in procs:
            try:
                cpu = proc.cpu_percent(interval=None)
                name = proc.name()
                if cpu and cpu > 1.0 and name:
                    results.append((name, cpu))
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        results.sort(key=lambda p: p[1], reverse=True)
        return results[:3], cpu_percent, load_avg