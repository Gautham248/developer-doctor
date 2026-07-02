import json
import shutil
import subprocess

from doctor.capabilities import Capability
from doctor.services.base import BaseService

DOCKER_TIMEOUT_SECONDS = 5


class DockerService(BaseService):
    """Shared, testable interface to the Docker CLI/daemon."""

    required_capability = Capability.DOCKER_DAEMON_ACCESS

    def is_installed(self) -> bool:
        return shutil.which("docker") is not None

    def get_info(self) -> dict | None:
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

    def get_total_container_memory_gb(self) -> float | None:
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