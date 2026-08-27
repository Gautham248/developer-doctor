import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from doctor.services.cleanup_service import CleanupService
from doctor.services.clean_service import CleanService


def test_cleanup_service_measure_path_file(tmp_path: Path):
    file_path = tmp_path / "test.txt"
    file_path.write_text("hello world")  # 11 bytes

    service = CleanupService()
    assert service.measure_path(file_path) == 11


def test_cleanup_service_measure_path_dir(tmp_path: Path):
    dir_path = tmp_path / "test_dir"
    dir_path.mkdir()
    (dir_path / "file1.txt").write_text("abc")  # 3 bytes
    (dir_path / "file2.txt").write_text("defgh")  # 5 bytes

    service = CleanupService()
    assert service.measure_path(dir_path) == 8


def test_cleanup_service_glob_size(tmp_path: Path):
    dir_path = tmp_path / "test_glob"
    dir_path.mkdir()
    (dir_path / "a.py").write_text("a")  # 1 byte
    (dir_path / "b.py").write_text("bc")  # 2 bytes
    (dir_path / "c.txt").write_text("def")  # 3 bytes

    service = CleanupService()
    # Check *.py size
    assert service.glob_size(dir_path, "*.py") == 3
    # Check *.txt size
    assert service.glob_size(dir_path, "*.txt") == 3


def test_cleanup_service_docker_disk_usage():
    service = CleanupService()

    # Sample docker system df line-delimited JSON output
    mock_stdout = (
        '{"Type":"Images","TotalCount":5,"Active":2,"Size":"1.5GB","Reclaimable":"1.2GB"}\n'
        '{"Type":"Containers","TotalCount":3,"Active":1,"Size":"150MB","Reclaimable":"50MB"}\n'
        '{"Type":"Local Volumes","TotalCount":2,"Active":1,"Size":"500MB","Reclaimable":"200MB"}\n'
        '{"Type":"Build Cache","TotalCount":10,"Active":0,"Size":"1.1GB","Reclaimable":"1GB"}\n'
    )
    mock_result = MagicMock(returncode=0, stdout=mock_stdout)

    with patch("shutil.which", return_value="/usr/local/bin/docker"), \
         patch("subprocess.run", return_value=mock_result):
        usage = service.docker_disk_usage()

    assert usage["images"] == 1.2 * 1000**3
    assert usage["containers"] == 50 * 1000**2
    assert usage["volumes"] == 200 * 1000**2
    assert usage["build_cache"] == 1 * 1000**3


def test_cleanup_service_parse_size_string():
    service = CleanupService()
    assert service._parse_size_string("1.2GB") == 1.2 * 1000**3
    assert service._parse_size_string("512MB") == 512 * 1000**2
    assert service._parse_size_string("10GiB") == 10 * 1024**3
    assert service._parse_size_string("0B") == 0


def test_clean_service_remove_path(tmp_path: Path):
    file_path = tmp_path / "del.txt"
    file_path.write_text("delete me")  # 9 bytes

    service = CleanService()
    assert service.remove_path(file_path) == 9
    assert not file_path.exists()


def test_clean_service_docker_prune():
    service = CleanService()
    mock_stdout = "Deleted Containers: ...\nTotal reclaimed space: 450.5MB\n"
    mock_result = MagicMock(returncode=0, stdout=mock_stdout)

    with patch("shutil.which", return_value="/usr/local/bin/docker"), \
         patch("subprocess.run", return_value=mock_result):
        freed = service.docker_prune_containers()

    assert freed == int(450.5 * 1000**2)
