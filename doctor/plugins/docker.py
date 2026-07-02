from doctor.capabilities import Capability
from doctor.models import Finding, PluginResult, Status
from doctor.plugins.base import DoctorPlugin
from doctor.services.docker_service import DockerService

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


class DockerPlugin(DoctorPlugin):
    name = "docker"
    description = "Checks whether Docker is installed, running, and reports container count/resource usage."
    capabilities = [Capability.DOCKER_DAEMON_ACCESS]

    def __init__(self, thresholds: dict[str, float] | None = None) -> None:
        self.thresholds = {**DEFAULT_THRESHOLDS, **(thresholds or {})}

    def is_supported(self) -> bool:
        return self.use_service(DockerService).is_installed()

    def run(self) -> PluginResult:
        try:
            docker_service = self.use_service(DockerService)
            info = docker_service.get_info()

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

            total_container_memory_gb = docker_service.get_total_container_memory_gb()
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