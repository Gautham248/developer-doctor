from unittest.mock import patch

from doctor.models import Status
from doctor.plugins.python import PythonPlugin


def test_detect_version_manager_mise():
    plugin = PythonPlugin()
    path = "/Users/dev/.local/share/mise/installs/python/3.13.0"
    assert plugin._detect_version_manager(path) == "mise"


def test_detect_version_manager_pyenv():
    plugin = PythonPlugin()
    path = "/Users/dev/.pyenv/versions/3.13.0"
    assert plugin._detect_version_manager(path) == "pyenv"


def test_python_plugin_passes_in_venv_reports_base_manager():
    plugin = PythonPlugin()
    with (
        patch.object(plugin, "_in_virtualenv", return_value=True),
        patch("sys.prefix", "/Users/dev/project/.venv"),
        patch("sys.base_prefix", "/Users/dev/.local/share/mise/installs/python/3.13.0"),
        patch.object(plugin, "_detect_venv_tool", return_value="uv"),
        patch.object(plugin, "_detect_conflicting_managers", return_value=["mise"]),
    ):
        result = plugin.run()

    assert result.status == Status.PASS
    assert result.score_delta == 0
    assert any("created by uv" in f.summary for f in result.findings)
    assert any("Base interpreter managed by: mise" in f.summary for f in result.findings)


def test_python_plugin_warns_when_no_venv_in_python_project():
    plugin = PythonPlugin()
    with (
        patch.object(plugin, "_in_virtualenv", return_value=False),
        patch("sys.base_prefix", "/usr/bin"),
        patch.object(plugin, "_cwd_looks_like_python_project", return_value=True),
        patch.object(plugin, "_detect_conflicting_managers", return_value=["mise"]),
    ):
        result = plugin.run()

    assert result.status == Status.WARN
    assert result.score_delta == 5


def test_python_plugin_passes_when_no_venv_outside_python_project():
    plugin = PythonPlugin()
    with (
        patch.object(plugin, "_in_virtualenv", return_value=False),
        patch("sys.base_prefix", "/usr/bin"),
        patch.object(plugin, "_cwd_looks_like_python_project", return_value=False),
        patch.object(plugin, "_detect_conflicting_managers", return_value=["mise"]),
    ):
        result = plugin.run()

    assert result.status == Status.PASS
    assert result.score_delta == 0


def test_python_plugin_warns_on_multiple_managers():
    plugin = PythonPlugin()
    with (
        patch.object(plugin, "_in_virtualenv", return_value=True),
        patch("sys.prefix", "/Users/dev/project/.venv"),
        patch("sys.base_prefix", "/Users/dev/.pyenv/versions/3.13.0"),
        patch.object(plugin, "_detect_venv_tool", return_value="venv"),
        patch.object(plugin, "_detect_conflicting_managers", return_value=["pyenv", "mise"]),
    ):
        result = plugin.run()

    assert result.status == Status.WARN
    assert result.score_delta == 5
    assert any("Multiple Python version managers" in f.summary for f in result.findings)


def test_python_plugin_never_raises_on_unexpected_failure():
    plugin = PythonPlugin()
    with patch.object(plugin, "_python_version", side_effect=RuntimeError("boom")):
        result = plugin.run()

    assert result.status == Status.FAIL
    assert "Could not run Python diagnostics" in result.findings[0].summary