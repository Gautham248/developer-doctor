from doctor.plugins.ai_ide import AIIDEPlugin
from doctor.plugins.base import DoctorPlugin
from doctor.plugins.battery import BatteryPlugin
from doctor.plugins.cpu import CPUPlugin
from doctor.plugins.disk import DiskPlugin
from doctor.plugins.docker import DockerPlugin
from doctor.plugins.git import GitPlugin
from doctor.plugins.memory import MemoryPlugin
from doctor.plugins.node import NodePlugin
from doctor.plugins.python import PythonPlugin
from doctor.plugins.system import SystemPlugin


def get_plugins() -> list[DoctorPlugin]:
    plugins: list[DoctorPlugin] = [
        SystemPlugin(),
        CPUPlugin(),
        MemoryPlugin(),
        BatteryPlugin(),
        DiskPlugin(),
        GitPlugin(),
        DockerPlugin(),
        NodePlugin(),
        PythonPlugin(),
        AIIDEPlugin(),
    ]
    return [p for p in plugins if p.is_supported()]