import json
import shutil
import subprocess

from doctor.models import Finding, PluginResult, Status
from doctor.plugins.base import DoctorPlugin
from doctor.capabilities import Capability

# Defaults — overridable per-project via doctor.toml:
# [thresholds.docker]
# warn_container_memory_gb = 6
# fail_container_memory_gb = 12
DEFAULT_THRESHOLDS = {
    "warn_container_memory_gb": 8.0,
    "fail_container_memory_gb": 16.0,
}

WARN_SCORE_DELTA = 5
FAIL_SCORE_DELTA = 15

DOCKER_TIMEOUT_SECONDS = 5


class DockerPlugin(DoctorPlugin):
    name = "docker"
    description = "Checks whether Docker is installed, running, and reports container count/resource usage."
    capabilities = [Capability.DOCKER_DAEMON_ACCESS, Capability.SHELL_COMMANDS]
    
    def __init__(self, thresholds: dict[str, float] | None = None) -> None:
        self.thresholds = {**DEFAULT_THRESHOLDS, **(thresholds or {})}

    def is_supported(self) -> bool:
        return shutil.which("docker") is not None

    def run(self) -> PluginResult:
        try:
            info = self._docker_info()

            if info is None:
                return PluginResult(
                    plugin_name=self.name,
                    status=Status.WARN,
                    score_delta=WARN_SCORE_DELTA,
                    findings=[Finding(summary="Docker is installed but the daemon is not running")],
                    recommendations=["Start Docker Desktop (or the Docker daemon) if you need it."],
                )

            container_count = info.get("Containers", 0)
            running_count = info.get("ContainersRunning", 0)

            findings = [
                Finding(summary="Docker daemon is running"),
                Finding(summary=f"{running_count} running / {container_count} total containers"),
            ]
            recommendations: list[str] = []
            status = Status.PASS
            score_delta = 0

            total_container_memory_gb = self._total_container_memory_gb()
            if total_container_memory_gb is not None:
                findings.append(
                    Finding(summary=f"Containers using {total_container_memory_gb:.1f} GB RAM")
                )

                if total_container_memory_gb >= self.thresholds["fail_container_memory_gb"]:
                    status = Status.FAIL
                    score_delta = FAIL_SCORE_DELTA
                    recommendations.append(
                        f"Containers are using {total_container_memory_gb:.1f} GB of RAM. "
                        f"Check for runaway or forgotten containers with 'docker stats'."
                    )
                elif total_container_memory_gb >= self.thresholds["warn_container_memory_gb"]:
                    status = Status.WARN
                    score_delta = WARN_SCORE_DELTA
                    recommendations.append(
                        f"Containers are using a notable amount of RAM "
                        f"({total_container_memory_gb:.1f} GB). Worth checking 'docker stats' "
                        f"if things feel slow."
                    )

            return PluginResult(
                plugin_name=self.name,
                status=status,
                score_delta=score_delta,
                findings=findings,
                recommendations=recommendations,
                metadata={
                    "container_count": container_count,
                    "running_count": running_count,
                    "total_container_memory_gb": total_container_memory_gb,
                },
            )
        except Exception as e:
            return PluginResult(
                plugin_name=self.name,
                status=Status.FAIL,
                findings=[Finding(summary="Could not run Docker diagnostics", detail=str(e))],
            )

    def _docker_info(self) -> dict | None:
        """Return `docker info` as a dict, or None if the daemon isn't reachable."""
        try:
            result = subprocess.run(
                ["docker", "info", "--format", "{{json .}}"],
                capture_output=True,
                text=True,
                timeout=DOCKER_TIMEOUT_SECONDS,
            )
            if result.returncode != 0:
                return None
            return json.loads(result.stdout)
        except (subprocess.SubprocessError, OSError, json.JSONDecodeError):
            return None

    def _total_container_memory_gb(self) -> float | None:
        """Sum memory usage across running containers via `docker stats`.

        Returns None if the check can't run (e.g. no running containers,
        or a transient docker CLI failure) — treated as inconclusive, not
        a failure.
        """
        try:
            result = subprocess.run(
                ["docker", "stats", "--no-stream", "--format", "{{.MemUsage}}"],
                capture_output=True,
                text=True,
                timeout=DOCKER_TIMEOUT_SECONDS,
            )
            if result.returncode != 0 or not result.stdout.strip():
                return None

            total_bytes = 0.0
            for line in result.stdout.strip().splitlines():
                used_part = line.split("/")[0].strip()
                total_bytes += self._parse_memory_string(used_part)

            return round(total_bytes / (1024**3), 2)
        except (subprocess.SubprocessError, OSError):
            return None

    def _parse_memory_string(self, value: str) -> float:
        """Parse a Docker memory string like '512MiB' or '1.2GiB' into bytes.

        Order matters: longer suffixes are checked first, since e.g.
        "512MiB" also ends with "B" and would otherwise wrongly match
        that shorter unit.
        """
        units = [("GiB", 1024**3), ("MiB", 1024**2), ("KiB", 1024), ("B", 1)]
        for unit, multiplier in units:
            if value.endswith(unit):
                number = value[: -len(unit)].strip()
                try:
                    return float(number) * multiplier
                except ValueError:
                    return 0.0
        return 0.0