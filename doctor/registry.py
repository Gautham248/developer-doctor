from doctor.config import DoctorConfig
from doctor.discovery import discover_entry_point_plugins, discover_user_plugins
from doctor.plugins.ai_ide import AIIDEPlugin
from doctor.plugins.base import DoctorPlugin
from doctor.plugins.battery import BatteryPlugin
from doctor.plugins.cpu import CPUPlugin
from doctor.plugins.disk import DiskPlugin
from doctor.plugins.docker import DockerPlugin
from doctor.plugins.git import GitPlugin
from doctor.plugins.memory import MemoryPlugin
from doctor.plugins.network import NetworkPlugin
from doctor.plugins.node import NodePlugin
from doctor.plugins.python import PythonPlugin
from doctor.plugins.system import SystemPlugin
from doctor.plugins.thermal import ThermalPlugin


def _builtin_plugins(cfg: DoctorConfig) -> list[DoctorPlugin]:
    return [
        SystemPlugin(),
        CPUPlugin(thresholds=cfg.thresholds.get("cpu")),
        ThermalPlugin(thresholds=cfg.thresholds.get("thermal")),
        MemoryPlugin(thresholds=cfg.thresholds.get("memory")),
        BatteryPlugin(thresholds=cfg.thresholds.get("battery")),
        DiskPlugin(thresholds=cfg.thresholds.get("disk")),
        NetworkPlugin(),
        GitPlugin(),
        DockerPlugin(thresholds=cfg.thresholds.get("docker")),
        NodePlugin(),
        PythonPlugin(),
        AIIDEPlugin(),
    ]


def discover_all_plugins(config: DoctorConfig | None = None) -> tuple[list[DoctorPlugin], list[str]]:
    """Discover built-in, user, and third-party (entry point) plugins.

    Built-in plugins always win on name collisions — a user or
    third-party plugin can never silently shadow a core diagnostic.
    Collisions are reported as warnings, not silently dropped.
    """
    cfg = config or DoctorConfig()
    errors: list[str] = []

    builtin = _builtin_plugins(cfg)
    seen_names = {p.name for p in builtin}

    user_plugins, user_errors = discover_user_plugins()
    errors.extend(user_errors)

    entry_point_plugins, entry_point_errors = discover_entry_point_plugins()
    errors.extend(entry_point_errors)

    all_plugins = list(builtin)
    for plugin in [*user_plugins, *entry_point_plugins]:
        if plugin.name in seen_names:
            errors.append(
                f"Plugin '{plugin.name}' from {type(plugin).__module__} was skipped: "
                f"a plugin with this name is already loaded"
            )
            continue
        all_plugins.append(plugin)
        seen_names.add(plugin.name)

    if cfg.plugins.enabled:
        selected = [p for p in all_plugins if p.name in cfg.plugins.enabled]
    else:
        selected = [p for p in all_plugins if p.name not in cfg.plugins.disabled]

    supported = [p for p in selected if p.is_supported()]
    return supported, errors


def get_plugins(config: DoctorConfig | None = None) -> list[DoctorPlugin]:
    """Backward-compatible convenience wrapper that discards discovery
    warnings. Prefer discover_all_plugins() when warnings should be
    surfaced (e.g. in the CLI)."""
    plugins, _ = discover_all_plugins(config)
    return plugins