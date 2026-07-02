from unittest.mock import patch

from doctor.models import Status
from doctor.plugins.docker import DockerPlugin
from doctor.services.docker_service import DockerService


def test_docker_plugin_not_supported_without_binary():
    plugin = DockerPlugin()
    with patch.object(DockerService, "is_installed", return_value=False):
        assert plugin.is_supported() is False


def test_docker_plugin_warns_when_daemon_not_running():
    plugin = DockerPlugin()
    with patch.object(DockerService, "get_info", return_value=None):
        result = plugin.run()

    assert result.status == Status.WARN
    assert result.score_delta == 5
    assert "daemon is not running" in result.findings[0].summary


def test_docker_plugin_passes_with_low_container_usage():
    plugin = DockerPlugin()
    with (
        patch.object(DockerService, "get_info", return_value={"Containers": 3, "ContainersRunning": 2}),
        patch.object(DockerService, "get_total_container_memory_gb", return_value=1.5),
    ):
        result = plugin.run()

    assert result.status == Status.PASS
    assert result.score_delta == 0


def test_docker_plugin_fails_on_heavy_container_memory():
    plugin = DockerPlugin()
    with (
        patch.object(DockerService, "get_info", return_value={"Containers": 5, "ContainersRunning": 5}),
        patch.object(DockerService, "get_total_container_memory_gb", return_value=18.0),
    ):
        result = plugin.run()

    assert result.status == Status.FAIL
    assert result.score_delta == 15


def test_docker_plugin_never_raises_on_unexpected_failure():
    plugin = DockerPlugin()
    with patch.object(DockerService, "get_info", side_effect=RuntimeError("boom")):
        result = plugin.run()

    assert result.status == Status.FAIL
    assert "Could not run Docker diagnostics" in result.findings[0].summary