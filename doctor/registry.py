from doctor.plugins.base import DoctorPlugin
from doctor.plugins.battery import BatteryPlugin
from doctor.plugins.cpu import CPUPlugin
from doctor.plugins.disk import DiskPlugin
from doctor.plugins.git import GitPlugin
from doctor.plugins.memory import MemoryPlugin
from doctor.plugins.system import SystemPlugin


def get_plugins() -> list[DoctorPlugin]:
    plugins: list[DoctorPlugin] = [
        SystemPlugin(),
        CPUPlugin(),
        MemoryPlugin(),
        BatteryPlugin(),
        DiskPlugin(),
        GitPlugin(),
    ]
    return [p for p in plugins if p.is_supported()]