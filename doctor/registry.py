from doctor.config import DoctorConfig
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


def get_plugins(config: DoctorConfig | None = None) -> list[DoctorPlugin]:
    cfg = config or DoctorConfig()

    all_plugins: list[DoctorPlugin] = [
        SystemPlugin(),
        CPUPlugin(thresholds=cfg.thresholds.get("cpu")),
        MemoryPlugin(thresholds=cfg.thresholds.get("memory")),
        BatteryPlugin(thresholds=cfg.thresholds.get("battery")),
        DiskPlugin(thresholds=cfg.thresholds.get("disk")),
        GitPlugin(),
        DockerPlugin(thresholds=cfg.thresholds.get("docker")),
        NodePlugin(),
        PythonPlugin(),
        AIIDEPlugin(),
    ]

    if cfg.plugins.enabled:
        selected = [p for p in all_plugins if p.name in cfg.plugins.enabled]
    else:
        selected = [p for p in all_plugins if p.name not in cfg.plugins.disabled]

    return [p for p in selected if p.is_supported()]