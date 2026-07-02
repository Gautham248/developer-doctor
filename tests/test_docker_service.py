import json
from unittest.mock import MagicMock, patch

from doctor.services.docker_service import DockerService


def test_is_installed_true_when_docker_on_path():
    service = DockerService()
    with patch("shutil.which", return_value="/usr/local/bin/docker"):
        assert service.is_installed() is True


def test_is_installed_false_when_docker_missing():
    service = DockerService()
    with patch("shutil.which", return_value=None):
        assert service.is_installed() is False


def test_get_info_parses_json_on_success():
    service = DockerService()
    mock_result = MagicMock(returncode=0, stdout=json.dumps({"Containers": 3}))
    with patch("subprocess.run", return_value=mock_result):
        assert service.get_info() == {"Containers": 3}


def test_get_info_returns_none_on_nonzero_exit():
    service = DockerService()
    mock_result = MagicMock(returncode=1, stdout="")
    with patch("subprocess.run", return_value=mock_result):
        assert service.get_info() is None


def test_get_info_returns_none_on_timeout():
    import subprocess as sp

    service = DockerService()
    with patch("subprocess.run", side_effect=sp.TimeoutExpired(cmd="docker", timeout=5)):
        assert service.get_info() is None


def test_get_total_container_memory_gb_sums_correctly():
    service = DockerService()
    mock_result = MagicMock(returncode=0, stdout="512MiB / 7.775GiB\n1.5GiB / 7.775GiB\n")
    with patch("subprocess.run", return_value=mock_result):
        total = service.get_total_container_memory_gb()
    assert total == round((512 * 1024**2 + 1.5 * 1024**3) / (1024**3), 2)


def test_get_total_container_memory_gb_none_when_no_output():
    service = DockerService()
    mock_result = MagicMock(returncode=0, stdout="")
    with patch("subprocess.run", return_value=mock_result):
        assert service.get_total_container_memory_gb() is None


def test_parse_memory_string_variants():
    service = DockerService()
    assert service._parse_memory_string("512MiB") == 512 * 1024**2
    assert service._parse_memory_string("1.5GiB") == 1.5 * 1024**3
    assert service._parse_memory_string("100B") == 100.0