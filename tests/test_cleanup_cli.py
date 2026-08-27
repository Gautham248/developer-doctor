from unittest.mock import MagicMock, patch
from typer.testing import CliRunner

from doctor.cli import app
from doctor.cleanup.base import BaseScanner
from doctor.models import CleanupCategory

runner = CliRunner()


class MockPythonScanner(BaseScanner):
    name = "python"
    label = "Python build caches"
    is_safe_to_auto_clean = True

    def is_supported(self) -> bool:
        return True

    def scan(self, cleanup_service) -> CleanupCategory:
        return CleanupCategory(
            name=self.name,
            label=self.label,
            size_bytes=100 * 1024**2,
            paths=["/path/to/pycache"],
            is_safe_to_auto_clean=self.is_safe_to_auto_clean,
        )

    def clean(self, clean_service, category_detail) -> int:
        return 100 * 1024**2


class MockNodeScanner(BaseScanner):
    name = "node"
    label = "Node modules"
    is_safe_to_auto_clean = False

    def is_supported(self) -> bool:
        return True

    def scan(self, cleanup_service) -> CleanupCategory:
        return CleanupCategory(
            name=self.name,
            label=self.label,
            size_bytes=200 * 1024**2,
            paths=["/path/to/node_modules"],
            is_safe_to_auto_clean=self.is_safe_to_auto_clean,
        )

    def clean(self, clean_service, category_detail) -> int:
        return 200 * 1024**2


def test_cleanup_cli_dry_run_default():
    with patch("doctor.cli.ALL_SCANNERS", [MockPythonScanner]), \
         patch("doctor.cli.typer.confirm", return_value=False) as mock_confirm:
        
        result = runner.invoke(app, ["cleanup"])

    assert result.exit_code == 0
    assert "Scanning for junk files..." in result.stdout
    assert "Python build caches" in result.stdout
    assert "100.0 MB" in result.stdout
    mock_confirm.assert_called_once()


def test_cleanup_cli_dry_run_explicit():
    with patch("doctor.cli.ALL_SCANNERS", [MockPythonScanner]):
        result = runner.invoke(app, ["cleanup", "--dry-run"])

    assert result.exit_code == 0
    assert "Dry-run mode active" in result.stdout


def test_cleanup_cli_yes_only_safe():
    # Only MockPythonScanner is safe to auto-clean, MockNodeScanner is not.
    with patch("doctor.cli.ALL_SCANNERS", [MockPythonScanner, MockNodeScanner]):
        result = runner.invoke(app, ["cleanup", "--yes"])

    assert result.exit_code == 0
    # Python is safe -> cleaned (100.0 MB)
    # Node is unsafe -> skipped
    assert "Skipping category 'node'" in result.stdout
    assert "Successfully reclaimed: 100.0 MB" in result.stdout


def test_cleanup_cli_yes_include_unsafe():
    with patch("doctor.cli.ALL_SCANNERS", [MockPythonScanner, MockNodeScanner]):
        result = runner.invoke(app, ["cleanup", "--yes", "--include-unsafe"])

    assert result.exit_code == 0
    # Both are cleaned (100.0 MB + 200.0 MB = 300.0 MB)
    assert "Successfully reclaimed: 300.0 MB" in result.stdout
