from pathlib import Path
from unittest.mock import MagicMock, patch
import sys

import pytest

from doctor.cleanup.docker_scanner import DockerScanner
from doctor.cleanup.xcode_scanner import XcodeScanner
from doctor.cleanup.python_scanner import PythonScanner
from doctor.cleanup.node_scanner import NodeScanner
from doctor.cleanup.macos_scanner import MacOSScanner
from doctor.cleanup.build_scanner import BuildScanner
from doctor.models import CleanupCategory


def test_docker_scanner_scan():
    scanner = DockerScanner()
    cleanup_service = MagicMock()
    cleanup_service.docker_disk_usage.return_value = {
        "images": 100 * 1024**2,
        "containers": 10 * 1024**2,
        "volumes": 0,
        "build_cache": 50 * 1024**2,
    }

    with patch("shutil.which", return_value="/usr/local/bin/docker"):
        assert scanner.is_supported() is True
        res = scanner.scan(cleanup_service)

    assert res.name == "docker"
    assert res.size_bytes == 160 * 1024**2
    assert res.is_safe_to_auto_clean is True
    assert len(res.paths) == 3


def test_docker_scanner_clean():
    scanner = DockerScanner()
    clean_service = MagicMock()
    clean_service.docker_prune_containers.return_value = 10
    clean_service.docker_prune_images.return_value = 20
    clean_service.docker_prune_build_cache.return_value = 30
    clean_service.docker_prune_volumes.return_value = 40

    freed = scanner.clean(clean_service, MagicMock())
    assert freed == 100


def test_xcode_scanner_scan_supported():
    scanner = XcodeScanner()
    cleanup_service = MagicMock()
    cleanup_service.measure_path.side_effect = lambda p: 100 if "DerivedData" in str(p) else 200

    with patch("sys.platform", "darwin"), \
         patch("pathlib.Path.exists", return_value=True):
        assert scanner.is_supported() is True
        res = scanner.scan(cleanup_service)

    assert res.name == "xcode"
    assert res.size_bytes == 300
    assert len(res.paths) == 2


def test_xcode_scanner_scan_unsupported():
    scanner = XcodeScanner()
    with patch("sys.platform", "linux"):
        assert scanner.is_supported() is False


def test_python_scanner_scan(tmp_path: Path):
    scanner = PythonScanner()
    cleanup_service = MagicMock()
    cleanup_service.measure_path.return_value = 50

    home = tmp_path / "home"
    home.mkdir()
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    # Create fake pycache directories to verify walk
    pycache = workspace / "src" / "__pycache__"
    pycache.mkdir(parents=True)
    (pycache / "foo.pyc").write_text("compiled")

    with patch("pathlib.Path.home", return_value=home), \
         patch("pathlib.Path.cwd", return_value=workspace):
        res = scanner.scan(cleanup_service)

    assert res.name == "python"
    assert res.size_bytes > 0


def test_node_scanner_scan_local_node_modules(tmp_path: Path):
    scanner = NodeScanner()
    cleanup_service = MagicMock()
    cleanup_service.measure_path.return_value = 1000

    home = tmp_path / "home"
    home.mkdir()
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    node_modules = workspace / "node_modules"
    node_modules.mkdir()

    with patch("pathlib.Path.home", return_value=home), \
         patch("pathlib.Path.cwd", return_value=workspace):
        res = scanner.scan(cleanup_service)

    assert res.name == "node"
    # Local node_modules was found, so it should NOT be safe to auto clean
    assert res.is_safe_to_auto_clean is False
    assert res.size_bytes >= 1000


def test_node_scanner_skips_workspace_scan_when_run_from_home(tmp_path: Path):
    scanner = NodeScanner()
    cleanup_service = MagicMock()
    cleanup_service.measure_path.return_value = 1000

    # User has some node_modules inside home/Library or home/.local
    fake_global_modules = tmp_path / ".local" / "share" / "mise" / "node_modules"
    fake_global_modules.mkdir(parents=True)

    with patch("pathlib.Path.home", return_value=tmp_path), \
         patch("pathlib.Path.cwd", return_value=tmp_path):
        res = scanner.scan(cleanup_service)

    # It should not have scanned or picked up the global node_modules from home
    assert not any("node_modules" in p for p in res.paths)
    assert res.is_safe_to_auto_clean is True


def test_macos_scanner_scan():
    scanner = MacOSScanner()
    cleanup_service = MagicMock()
    cleanup_service.measure_path.return_value = 500
    cleanup_service.get_brew_cache_path.return_value = Path("/home/user/Library/Caches/Homebrew")

    with patch("sys.platform", "darwin"), \
         patch("pathlib.Path.exists", return_value=True):
        res = scanner.scan(cleanup_service)

    assert res.name == "macos"
    assert res.size_bytes == 1000


def test_build_scanner_scan(tmp_path: Path):
    scanner = BuildScanner()
    cleanup_service = MagicMock()
    cleanup_service.measure_path.return_value = 250

    home = tmp_path / "home"
    home.mkdir()
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    target = workspace / "target"
    target.mkdir()

    with patch("pathlib.Path.home", return_value=home), \
         patch("pathlib.Path.cwd", return_value=workspace):
        res = scanner.scan(cleanup_service)

    assert res.name == "build"
    assert res.size_bytes >= 250


def test_build_scanner_ignores_node_modules_dist(tmp_path: Path):
    scanner = BuildScanner()
    cleanup_service = MagicMock()
    cleanup_service.measure_path.return_value = 250

    home = tmp_path / "home"
    home.mkdir()
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    # Package inside node_modules has a dist directory
    pkg_dist = workspace / "node_modules" / "some-package" / "dist"
    pkg_dist.mkdir(parents=True)

    # Also a real workspace dist directory
    real_dist = workspace / "dist"
    real_dist.mkdir()

    with patch("pathlib.Path.home", return_value=home), \
         patch("pathlib.Path.cwd", return_value=workspace):
        res = scanner.scan(cleanup_service)

    assert res.name == "build"
    # Should only contain real_dist, never node_modules/some-package/dist
    assert str(real_dist) in res.paths
    assert not any("node_modules" in p for p in res.paths)


def test_build_scanner_skips_workspace_scan_when_run_from_home(tmp_path: Path):
    scanner = BuildScanner()
    cleanup_service = MagicMock()

    with patch("pathlib.Path.home", return_value=tmp_path), \
         patch("pathlib.Path.cwd", return_value=tmp_path):
        res = scanner.scan(cleanup_service)

    # When run from home, no local workspace paths should be collected
    workspace_collected = [p for p in res.paths if not p.startswith(str(tmp_path / ".m2")) and not p.startswith(str(tmp_path / ".cargo")) and not p.startswith(str(tmp_path / ".gradle"))]
    assert len(workspace_collected) == 0
