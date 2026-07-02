import importlib.metadata
import importlib.util
import inspect
import sys
from pathlib import Path
from types import ModuleType

from doctor.plugins.base import DoctorPlugin

ENTRY_POINT_GROUP = "doctor.plugins"


def user_plugin_dir() -> Path:
    return Path.home() / ".config" / "doctor" / "plugins"


def discover_user_plugins() -> tuple[list[DoctorPlugin], list[str]]:
    """Load plugins from ~/.config/doctor/plugins/*.py.

    Each file may define one or more DoctorPlugin subclasses; every
    concrete subclass found is instantiated with no arguments. A broken
    file (syntax error, bad import, exception at class-definition time)
    is skipped and reported as a load error string — it must never
    crash discovery for the rest of the plugins (§6.4).
    """
    directory = user_plugin_dir()
    plugins: list[DoctorPlugin] = []
    errors: list[str] = []

    if not directory.is_dir():
        return plugins, errors

    for file_path in sorted(directory.glob("*.py")):
        if file_path.name.startswith("_"):
            continue
        try:
            module = _load_module_from_path(file_path)
            plugins.extend(_extract_plugin_instances(module))
        except Exception as e:
            errors.append(f"Failed to load user plugin '{file_path.name}': {e}")

    return plugins, errors


def discover_entry_point_plugins() -> tuple[list[DoctorPlugin], list[str]]:
    """Load third-party plugins registered under the 'doctor.plugins'
    entry point group (e.g. a pip-installed doctor-plugin-kubernetes).

    Per §6.3: `pip install doctor-kubernetes` should make the plugin
    available with no further configuration, via standard packaging
    metadata rather than any doctor-specific registration step.
    """
    plugins: list[DoctorPlugin] = []
    errors: list[str] = []

    try:
        entry_points = importlib.metadata.entry_points(group=ENTRY_POINT_GROUP)
    except Exception as e:
        errors.append(f"Failed to read plugin entry points: {e}")
        return plugins, errors

    for entry_point in entry_points:
        try:
            plugin_class = entry_point.load()
            if inspect.isclass(plugin_class) and issubclass(plugin_class, DoctorPlugin):
                plugins.append(plugin_class())
            else:
                errors.append(
                    f"Entry point '{entry_point.name}' does not point to a DoctorPlugin subclass"
                )
        except Exception as e:
            errors.append(f"Failed to load plugin entry point '{entry_point.name}': {e}")

    return plugins, errors


def _load_module_from_path(file_path: Path) -> ModuleType:
    module_name = f"doctor_user_plugin_{file_path.stem}"
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not create module spec for {file_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _extract_plugin_instances(module: ModuleType) -> list[DoctorPlugin]:
    instances = []
    for _, obj in inspect.getmembers(module, inspect.isclass):
        if issubclass(obj, DoctorPlugin) and obj is not DoctorPlugin:
            instances.append(obj())
    return instances

def load_plugins_from_file(file_path: Path) -> tuple[list[DoctorPlugin], list[str]]:
    """Load and instantiate all DoctorPlugin subclasses defined in a
    single .py file — used by `doctor plugin validate` (§22.5) to let
    plugin authors sanity-check a plugin before publishing, using the
    exact same loading mechanism discover_user_plugins() uses at
    runtime, so a pass here means the plugin will actually load for
    real users too."""
    try:
        module = _load_module_from_path(file_path)
        return _extract_plugin_instances(module), []
    except Exception as e:
        return [], [f"Failed to load '{file_path.name}': {e}"]