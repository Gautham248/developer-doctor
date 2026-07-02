import platform
import time

import psutil

from doctor.models import Finding, PluginResult, Status
from doctor.plugins.base import DoctorPlugin


class SystemPlugin(DoctorPlugin):
    name = "system"
    description = "Reports basic system information: OS, architecture, RAM, uptime."

    def run(self) -> PluginResult:
        try:
            uname = platform.uname()
            total_ram_gb = round(psutil.virtual_memory().total / (1024**3), 1)
            uptime_seconds = time.time() - psutil.boot_time()
            uptime_hours = round(uptime_seconds / 3600, 1)

            return PluginResult(
                plugin_name=self.name,
                status=Status.INFO,
                findings=[
                    Finding(
                        summary=f"{uname.system} {uname.release} ({uname.machine})",
                    ),
                    Finding(summary=f"{total_ram_gb} GB RAM"),
                    Finding(summary=f"Uptime: {uptime_hours} hours"),
                ],
                metadata={
                    "os": uname.system,
                    "os_release": uname.release,
                    "architecture": uname.machine,
                    "total_ram_gb": total_ram_gb,
                    "uptime_hours": uptime_hours,
                },
            )
        except Exception as e:
            return PluginResult(
                plugin_name=self.name,
                status=Status.FAIL,
                findings=[Finding(summary="Could not read system information", detail=str(e))],
            )