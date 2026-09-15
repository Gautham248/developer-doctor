import time
from collections.abc import Callable
from dataclasses import dataclass

import psutil

from doctor.capabilities import Capability
from doctor.services.base import BaseService
from doctor.services.thermal_service import KillSafety, ThermalService

DEFAULT_SAMPLE_INTERVAL_SECONDS = 0.5


@dataclass
class MemoryProcess:
    """A process ranked by RAM (RSS) usage, with the same kill-safety
    rating ThermalService already computes for CPU-ranked processes —
    reused here rather than re-implemented (§12: shared, testable
    services; avoid duplicating the same classification twice)."""

    pid: int
    name: str
    rss_gb: float
    username: str
    ppid: int
    kill_safety: KillSafety
    kill_reason: str


class ProcessService(BaseService):
    """Shared, testable interface to process/CPU sampling.

    Centralizes the "prime cpu_percent(), sleep once, then read the
    real value" pattern psutil requires for meaningful per-process CPU%
    readings — the first call after discovering a process handle
    returns 0.0 or garbage, since psutil needs a baseline to diff
    against. This was previously duplicated almost verbatim in
    CPUPlugin and AIIDEPlugin; consolidating it here is the actual
    duplication §12 is meant to eliminate, not a token example.
    """

    required_capability = Capability.PROCESS_INSPECTION

    def sample_system_and_processes(
        self,
        limit: int = 3,
        min_cpu_percent: float = 1.0,
        sample_interval: float = DEFAULT_SAMPLE_INTERVAL_SECONDS,
    ) -> tuple[list[tuple[str, float]], float, tuple[float, float, float]]:
        """Single shared-sample-window read of system CPU%, load average,
        and top processes by CPU% — one sleep, not one per metric."""
        psutil.cpu_percent(interval=None)
        procs = self._prime(process_filter=None)

        time.sleep(sample_interval)

        cpu_percent = psutil.cpu_percent(interval=None)
        load_avg = psutil.getloadavg()

        results = []
        for proc in procs:
            try:
                cpu = proc.cpu_percent(interval=None)
                name = proc.name()
                if cpu and cpu > min_cpu_percent and name:
                    results.append((name, cpu))
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        results.sort(key=lambda p: p[1], reverse=True)
        return results[:limit], cpu_percent, load_avg

    def sample_memory_processes(
        self,
        limit: int = 5,
        min_rss_gb: float = 0.1,
    ) -> list[MemoryProcess]:
        """Return the top RAM-consuming processes with kill safety ratings.

        Unlike CPU%, RSS is a point-in-time value psutil can read on the
        first call — no prime/sleep window needed, so this is cheap enough
        to call only when a memory finding is already WARN/FAIL (see
        MemoryPlugin), keeping the common PASS-path fast (§2.1: under 3s).
        """
        current_user = ThermalService._current_username()
        results: list[MemoryProcess] = []

        for proc in psutil.process_iter(["pid", "name", "username", "ppid"]):
            try:
                rss_gb = proc.memory_info().rss / (1024**3)
                if rss_gb < min_rss_gb:
                    continue

                info = proc.as_dict(attrs=["pid", "name", "username", "ppid"])
                name = info.get("name") or ""
                username = info.get("username") or ""
                pid = info.get("pid", 0)
                ppid = info.get("ppid", 0)

                safety, reason = ThermalService._classify_kill_safety(
                    pid=pid,
                    name=name,
                    username=username,
                    current_user=current_user,
                )
                results.append(
                    MemoryProcess(
                        pid=pid,
                        name=name,
                        rss_gb=rss_gb,
                        username=username,
                        ppid=ppid,
                        kill_safety=safety,
                        kill_reason=reason,
                    )
                )
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        results.sort(key=lambda p: p.rss_gb, reverse=True)
        return results[:limit]

    def sample_grouped(
        self,
        classify: Callable[[str], str | None],
        sample_interval: float = DEFAULT_SAMPLE_INTERVAL_SECONDS,
    ) -> dict[str, dict[str, float]]:
        """Aggregate CPU%/RAM/process-count for processes matched by
        `classify`. `classify(process_name)` returns a group label, or
        None to exclude that process entirely."""
        matched = self._prime(process_filter=classify)
        if not matched:
            return {}

        time.sleep(sample_interval)

        groups: dict[str, dict[str, float]] = {}
        for proc in matched:
            try:
                name = proc.name()
                label = classify(name) if name else None
                if not label:
                    continue
                cpu = proc.cpu_percent(interval=None)
                ram_gb = proc.memory_info().rss / (1024**3)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

            if label not in groups:
                groups[label] = {"cpu_percent": 0.0, "ram_gb": 0.0, "process_count": 0.0}
            groups[label]["cpu_percent"] += cpu
            groups[label]["ram_gb"] += ram_gb
            groups[label]["process_count"] += 1

        return groups

    def _prime(
        self, process_filter: Callable[[str], str | None] | None
    ) -> list[psutil.Process]:
        """Prime cpu_percent() counters for matching processes (or all,
        if no filter) — the required first call before a meaningful
        second read."""
        primed = []
        for proc in psutil.process_iter(["name"]):
            try:
                name = proc.info["name"]
                if process_filter is not None:
                    if not name or process_filter(name) is None:
                        continue
                proc.cpu_percent(interval=None)
                primed.append(proc)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return primed