"""Shared thermal monitoring service.

Provides a unified interface to read thermal pressure, power consumption,
and enriched process data across macOS (Apple Silicon) and Linux.

macOS primary path: sudo powermetrics — gives thermal pressure level +
CPU/GPU/ANE power in mW. Falls back to a Swift one-liner
(NSProcessInfo.thermalState) if sudo is unavailable or times out.

Linux: reads /sys/class/thermal/thermal_zone*/temp (no root required).
"""

from __future__ import annotations

import os
import platform
import re
import subprocess
import time
from dataclasses import dataclass, field
from enum import Enum

import psutil

from doctor.capabilities import Capability
from doctor.services.base import BaseService

# ---------------------------------------------------------------------------
# Public data types
# ---------------------------------------------------------------------------

LEVEL_NOMINAL = "nominal"
LEVEL_FAIR = "fair"
LEVEL_SERIOUS = "serious"
LEVEL_CRITICAL = "critical"
LEVEL_UNKNOWN = "unknown"

SOURCE_MACOS_POWERMETRICS = "macos_powermetrics"
SOURCE_MACOS_SWIFT = "macos_swift_fallback"
SOURCE_LINUX_SYSFS = "linux_sysfs"
SOURCE_UNAVAILABLE = "unavailable"


class KillSafety(str, Enum):
    SAFE = "SAFE"
    CAUTION = "CAUTION"
    UNSAFE = "UNSAFE"


@dataclass
class ThermalState:
    level: str  # LEVEL_* constants above
    temperature_c: float | None = None  # Linux only; None on macOS
    cpu_power_mw: float | None = None   # macOS sudo powermetrics path
    gpu_power_mw: float | None = None
    ane_power_mw: float | None = None
    source: str = SOURCE_UNAVAILABLE
    pmset_warnings: bool = False


@dataclass
class ThermalProcess:
    pid: int
    name: str
    cpu_percent: float
    username: str
    ppid: int
    kill_safety: KillSafety
    kill_reason: str


# ---------------------------------------------------------------------------
# Known system-critical process names — never safe to kill
# ---------------------------------------------------------------------------
_UNSAFE_NAMES: frozenset[str] = frozenset({
    "kernel_task",
    "launchd",
    "WindowServer",
    "loginwindow",
    "mds",          # Spotlight metadata server (root-owned)
    "syslogd",
    "configd",
    "distnoted",
    "securityd",
    "trustd",
    "watchdogd",
    "thermalmonitord",
    "thermald",
})

# Known system daemons that are CAUTION (root-owned but not instantly dangerous)
_CAUTION_NAMES: frozenset[str] = frozenset({
    "logd",
    "smd",
    "mds_stores",
    "mdworker",
    "UserEventAgent",
    "mDNSResponder",
    "nsurlsessiond",
    "cloudd",
    "bird",
    "rapportd",
    "bluetoothd",
    "airportd",
    "wifid",
    "diagnosticd",
    "notifyd",
    "opendirectoryd",
})

# Default sample interval for psutil priming
_SAMPLE_INTERVAL = 0.5


# ---------------------------------------------------------------------------
# ThermalService
# ---------------------------------------------------------------------------

class ThermalService(BaseService):
    """Shared thermal data service for ThermalPlugin and CLI commands."""

    required_capability = Capability.THERMAL_MONITORING

    # -- Thermal state -------------------------------------------------------

    def get_thermal_state(self) -> ThermalState:
        """Return the current system thermal state.

        On macOS: tries sudo powermetrics first; falls back to Swift one-liner.
        On Linux: reads /sys/class/thermal sysfs nodes.
        """
        system = platform.system()
        if system == "Darwin":
            state = self._read_macos_powermetrics()
            if state is not None:
                return state
            return self._read_macos_swift()
        elif system == "Linux":
            return self._read_linux_sysfs()
        return ThermalState(level=LEVEL_UNKNOWN, source=SOURCE_UNAVAILABLE)

    def _read_macos_powermetrics(self) -> ThermalState | None:
        """Run sudo powermetrics for one sample and parse power + thermal level.

        Returns None on any failure so the caller can fall through to Swift.
        """
        try:
            result = subprocess.run(
                [
                    "sudo",
                    "powermetrics",
                    "-n", "1",
                    "-i", "1000",
                    "--samplers", "cpu_power,gpu_power,ane_power,thermal",
                    "--format", "text",
                ],
                capture_output=True,
                text=True,
                timeout=20,
            )
            if result.returncode != 0:
                return None

            text = result.stdout

            # Parse power values
            cpu_mw = self._parse_mw(text, r"CPU Power:\s+([\d.]+)\s+mW")
            gpu_mw = self._parse_mw(text, r"GPU Power:\s+([\d.]+)\s+mW")
            ane_mw = self._parse_mw(text, r"ANE Power:\s+([\d.]+)\s+mW")

            # Parse thermal pressure level
            level_match = re.search(
                r"Thermal pressure:\s+(\w+)", text, re.IGNORECASE
            )
            level = LEVEL_NOMINAL
            if level_match:
                raw = level_match.group(1).lower()
                level = {
                    "nominal": LEVEL_NOMINAL,
                    "fair": LEVEL_FAIR,
                    "serious": LEVEL_SERIOUS,
                    "critical": LEVEL_CRITICAL,
                }.get(raw, LEVEL_UNKNOWN)

            pmset_warn = self._check_pmset_warnings()

            return ThermalState(
                level=level,
                cpu_power_mw=cpu_mw,
                gpu_power_mw=gpu_mw,
                ane_power_mw=ane_mw,
                source=SOURCE_MACOS_POWERMETRICS,
                pmset_warnings=pmset_warn,
            )
        except (subprocess.TimeoutExpired, subprocess.SubprocessError, OSError):
            return None

    def _read_macos_swift(self) -> ThermalState:
        """Read NSProcessInfo.thermalState via a swift one-liner (no sudo).

        Returns LEVEL_UNKNOWN on any failure.
        """
        try:
            result = subprocess.run(
                [
                    "swift",
                    "-e",
                    "import Foundation; "
                    "print(ProcessInfo.processInfo.thermalState.rawValue)",
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                raw = result.stdout.strip()
                level = {
                    "0": LEVEL_NOMINAL,
                    "1": LEVEL_FAIR,
                    "2": LEVEL_SERIOUS,
                    "3": LEVEL_CRITICAL,
                }.get(raw, LEVEL_UNKNOWN)
                pmset_warn = self._check_pmset_warnings()
                return ThermalState(
                    level=level,
                    source=SOURCE_MACOS_SWIFT,
                    pmset_warnings=pmset_warn,
                )
        except (subprocess.TimeoutExpired, subprocess.SubprocessError, OSError):
            pass
        return ThermalState(level=LEVEL_UNKNOWN, source=SOURCE_UNAVAILABLE)

    def _read_linux_sysfs(self) -> ThermalState:
        """Read temperature from /sys/class/thermal/thermal_zone*/temp."""
        try:
            thermal_root = "/sys/class/thermal"
            if not os.path.isdir(thermal_root):
                return ThermalState(level=LEVEL_UNKNOWN, source=SOURCE_UNAVAILABLE)

            max_temp_c: float | None = None
            for zone in os.listdir(thermal_root):
                if not zone.startswith("thermal_zone"):
                    continue
                temp_file = os.path.join(thermal_root, zone, "temp")
                try:
                    with open(temp_file) as f:
                        raw = int(f.read().strip())
                    temp_c = raw / 1000.0
                    if max_temp_c is None or temp_c > max_temp_c:
                        max_temp_c = temp_c
                except (OSError, ValueError):
                    continue

            if max_temp_c is None:
                return ThermalState(level=LEVEL_UNKNOWN, source=SOURCE_UNAVAILABLE)

            if max_temp_c >= 85:
                level = LEVEL_CRITICAL
            elif max_temp_c >= 75:
                level = LEVEL_SERIOUS
            elif max_temp_c >= 60:
                level = LEVEL_FAIR
            else:
                level = LEVEL_NOMINAL

            return ThermalState(
                level=level,
                temperature_c=max_temp_c,
                source=SOURCE_LINUX_SYSFS,
            )
        except Exception:
            return ThermalState(level=LEVEL_UNKNOWN, source=SOURCE_UNAVAILABLE)

    def _check_pmset_warnings(self) -> bool:
        """Return True if pmset -g therm reports any recorded warnings."""
        try:
            result = subprocess.run(
                ["pmset", "-g", "therm"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            text = result.stdout
            # "No thermal warning level has been recorded" means clean
            return "No thermal warning" not in text and "No performance warning" not in text
        except Exception:
            return False

    @staticmethod
    def _parse_mw(text: str, pattern: str) -> float | None:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                pass
        return None

    # -- Process list -------------------------------------------------------

    def get_thermal_processes(
        self,
        limit: int = 10,
        min_cpu_percent: float = 0.5,
        sample_interval: float = _SAMPLE_INTERVAL,
    ) -> list[ThermalProcess]:
        """Return the top CPU-consuming processes with kill safety ratings.

        Uses psutil's two-sample pattern (prime → sleep → read) to get
        meaningful CPU% values rather than the zero-or-garbage first read.
        """
        # Prime
        procs: list[psutil.Process] = []
        for proc in psutil.process_iter(["name", "pid", "username", "ppid"]):
            try:
                proc.cpu_percent(interval=None)
                procs.append(proc)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        time.sleep(sample_interval)

        results: list[ThermalProcess] = []
        current_user = self._current_username()

        for proc in procs:
            try:
                cpu = proc.cpu_percent(interval=None)
                if cpu < min_cpu_percent:
                    continue
                info = proc.as_dict(attrs=["pid", "name", "username", "ppid"])
                name = info.get("name") or ""
                username = info.get("username") or ""
                pid = info.get("pid", 0)
                ppid = info.get("ppid", 0)

                safety, reason = self._classify_kill_safety(
                    pid=pid,
                    name=name,
                    username=username,
                    current_user=current_user,
                )
                results.append(
                    ThermalProcess(
                        pid=pid,
                        name=name,
                        cpu_percent=cpu,
                        username=username,
                        ppid=ppid,
                        kill_safety=safety,
                        kill_reason=reason,
                    )
                )
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        results.sort(key=lambda p: p.cpu_percent, reverse=True)
        return results[:limit]

    @staticmethod
    def _current_username() -> str:
        try:
            import getpass
            return getpass.getuser()
        except Exception:
            return ""

    @staticmethod
    def _classify_kill_safety(
        pid: int,
        name: str,
        username: str,
        current_user: str,
    ) -> tuple[KillSafety, str]:
        """Return (KillSafety, human-readable reason)."""
        base_name = name.split("(")[0].strip()  # strip " (Renderer)" etc.

        if pid <= 1:
            return KillSafety.UNSAFE, "kernel or init process"
        if name in _UNSAFE_NAMES or base_name in _UNSAFE_NAMES:
            return KillSafety.UNSAFE, "critical system process"
        if username == "root" and (name in _CAUTION_NAMES or base_name in _CAUTION_NAMES):
            return KillSafety.CAUTION, "system daemon — killing may affect stability"
        if username == "root":
            return KillSafety.CAUTION, "root-owned process — treat with care"
        if current_user and username == current_user:
            return KillSafety.SAFE, "user-owned process"
        return KillSafety.CAUTION, "unknown ownership"
