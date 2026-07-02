from doctor.config import DoctorConfig, PluginsConfig
from doctor.registry import get_plugins


def test_get_plugins_returns_all_supported_plugins_by_default():
    plugins = get_plugins()
    names = {p.name for p in plugins}
    assert "system" in names
    assert "cpu" in names


def test_get_plugins_respects_disabled_list():
    config = DoctorConfig(plugins=PluginsConfig(disabled=["docker", "git"]))
    plugins = get_plugins(config)
    names = {p.name for p in plugins}
    assert "docker" not in names
    assert "git" not in names
    assert "system" in names


def test_get_plugins_respects_enabled_whitelist():
    config = DoctorConfig(plugins=PluginsConfig(enabled=["system", "cpu"]))
    plugins = get_plugins(config)
    names = {p.name for p in plugins}
    assert names == {"system", "cpu"}


def test_get_plugins_applies_cpu_threshold_overrides():
    config = DoctorConfig(thresholds={"cpu": {"warn_percent": 10.0}})
    plugins = get_plugins(config)
    cpu_plugin = next(p for p in plugins if p.name == "cpu")
    assert cpu_plugin.thresholds["warn_percent"] == 10.0  # type: ignore[attr-defined]