import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

from doctor.discovery import discover_entry_point_plugins, discover_user_plugins

VALID_PLUGIN_SOURCE = textwrap.dedent(
    """
    from doctor.models import Finding, PluginResult, Status
    from doctor.plugins.base import DoctorPlugin


    class FakePlugin(DoctorPlugin):
        name = "fake_user_plugin"
        description = "A fake user plugin for testing."

        def run(self) -> PluginResult:
            return PluginResult(
                plugin_name=self.name,
                status=Status.PASS,
                findings=[Finding(summary="ok")],
            )
    """
)

BROKEN_PLUGIN_SOURCE = "this is not valid python ("


def test_discover_user_plugins_returns_empty_when_dir_missing(tmp_path: Path):
    missing_dir = tmp_path / "does_not_exist"
    with patch("doctor.discovery.user_plugin_dir", return_value=missing_dir):
        plugins, errors = discover_user_plugins()

    assert plugins == []
    assert errors == []


def test_discover_user_plugins_loads_valid_plugin(tmp_path: Path):
    (tmp_path / "fake_plugin.py").write_text(VALID_PLUGIN_SOURCE)
    with patch("doctor.discovery.user_plugin_dir", return_value=tmp_path):
        plugins, errors = discover_user_plugins()

    assert len(plugins) == 1
    assert plugins[0].name == "fake_user_plugin"
    assert errors == []


def test_discover_user_plugins_reports_error_for_broken_file(tmp_path: Path):
    (tmp_path / "broken.py").write_text(BROKEN_PLUGIN_SOURCE)
    with patch("doctor.discovery.user_plugin_dir", return_value=tmp_path):
        plugins, errors = discover_user_plugins()

    assert plugins == []
    assert len(errors) == 1
    assert "broken.py" in errors[0]


def test_discover_user_plugins_skips_underscore_files(tmp_path: Path):
    (tmp_path / "_helper.py").write_text(VALID_PLUGIN_SOURCE)
    with patch("doctor.discovery.user_plugin_dir", return_value=tmp_path):
        plugins, errors = discover_user_plugins()

    assert plugins == []
    assert errors == []


def test_discover_user_plugins_continues_after_one_broken_file(tmp_path: Path):
    (tmp_path / "broken.py").write_text(BROKEN_PLUGIN_SOURCE)
    (tmp_path / "fake_plugin.py").write_text(VALID_PLUGIN_SOURCE)
    with patch("doctor.discovery.user_plugin_dir", return_value=tmp_path):
        plugins, errors = discover_user_plugins()

    assert len(plugins) == 1
    assert plugins[0].name == "fake_user_plugin"
    assert len(errors) == 1


def test_discover_entry_point_plugins_loads_valid_plugin():
    from doctor.models import Finding, PluginResult, Status
    from doctor.plugins.base import DoctorPlugin

    class FakeEntryPointPlugin(DoctorPlugin):
        name = "fake_entry_point_plugin"
        description = "fake"

        def run(self) -> PluginResult:
            return PluginResult(
                plugin_name=self.name, status=Status.PASS, findings=[Finding(summary="ok")]
            )

    fake_entry_point = MagicMock()
    fake_entry_point.name = "fake_entry_point_plugin"
    fake_entry_point.load.return_value = FakeEntryPointPlugin

    with patch("importlib.metadata.entry_points", return_value=[fake_entry_point]):
        plugins, errors = discover_entry_point_plugins()

    assert len(plugins) == 1
    assert plugins[0].name == "fake_entry_point_plugin"
    assert errors == []


def test_discover_entry_point_plugins_reports_error_on_load_failure():
    fake_entry_point = MagicMock()
    fake_entry_point.name = "broken_plugin"
    fake_entry_point.load.side_effect = ImportError("boom")

    with patch("importlib.metadata.entry_points", return_value=[fake_entry_point]):
        plugins, errors = discover_entry_point_plugins()

    assert plugins == []
    assert len(errors) == 1
    assert "broken_plugin" in errors[0]


def test_discover_entry_point_plugins_rejects_non_plugin_class():
    fake_entry_point = MagicMock()
    fake_entry_point.name = "not_a_plugin"
    fake_entry_point.load.return_value = str

    with patch("importlib.metadata.entry_points", return_value=[fake_entry_point]):
        plugins, errors = discover_entry_point_plugins()

    assert plugins == []
    assert len(errors) == 1 

def test_discover_all_plugins_returns_plugins_and_errors():
    from doctor.registry import discover_all_plugins

    plugins, errors = discover_all_plugins()
    assert isinstance(plugins, list)
    assert isinstance(errors, list)
    assert any(p.name == "system" for p in plugins)


def test_discover_all_plugins_builtin_wins_name_collision():
    from unittest.mock import patch

    from doctor.models import Finding, PluginResult, Status
    from doctor.plugins.base import DoctorPlugin
    from doctor.registry import discover_all_plugins

    class FakeSystemPlugin(DoctorPlugin):
        name = "system"
        description = "fake"

        def run(self) -> PluginResult:
            return PluginResult(
                plugin_name=self.name, status=Status.PASS, findings=[Finding(summary="fake")]
            )

    with patch("doctor.registry.discover_user_plugins", return_value=([FakeSystemPlugin()], [])):
        plugins, errors = discover_all_plugins()

    system_plugins = [p for p in plugins if p.name == "system"]
    assert len(system_plugins) == 1
    assert not isinstance(system_plugins[0], FakeSystemPlugin)
    assert any("already loaded" in e for e in errors)