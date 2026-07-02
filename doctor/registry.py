from doctor.plugins.base import DoctorPlugin
from doctor.plugins.battery import BatteryPlugin
from doctor.plugins.cpu import CPUPlugin
from doctor.plugins.memory import MemoryPlugin
from doctor.plugins.system import SystemPlugin


def get_plugins() -> list[DoctorPlugin]:
    plugins: list[DoctorPlugin] = [
        SystemPlugin(),
        CPUPlugin(),
        MemoryPlugin(),
        BatteryPlugin(),
    ]
    return [p for p in plugins if p.is_supported()]