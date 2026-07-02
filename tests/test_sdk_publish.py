from pathlib import Path
from unittest.mock import MagicMock, patch

from doctor.sdk.publish import check_package, upload_package


def test_check_package_fails_without_artifacts(tmp_path: Path):
    result = check_package(tmp_path)
    assert result.success is False
    assert "No built artifacts" in result.output


def test_check_package_fails_without_twine(tmp_path: Path):
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    (dist_dir / "x.whl").write_text("fake")
    with patch("shutil.which", return_value=None):
        result = check_package(tmp_path)

    assert result.success is False
    assert "twine" in result.output.lower()


def test_check_package_succeeds(tmp_path: Path):
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    (dist_dir / "x.whl").write_text("fake")
    mock_result = MagicMock(returncode=0, stdout="Checking x.whl: PASSED", stderr="")
    with (
        patch("shutil.which", return_value="/usr/bin/twine"),
        patch("subprocess.run", return_value=mock_result),
    ):
        result = check_package(tmp_path)

    assert result.success is True
    assert result.dry_run is True


def test_upload_package_fails_without_artifacts(tmp_path: Path):
    result = upload_package(tmp_path, "testpypi")
    assert result.success is False
    assert result.dry_run is False


def test_upload_package_calls_twine_with_repository(tmp_path: Path):
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    (dist_dir / "x.whl").write_text("fake")
    mock_result = MagicMock(returncode=0, stdout="Uploaded", stderr="")
    with (
        patch("shutil.which", return_value="/usr/bin/twine"),
        patch("subprocess.run", return_value=mock_result) as mock_run,
    ):
        result = upload_package(tmp_path, "testpypi")

    assert result.success is True
    called_args = mock_run.call_args[0][0]
    assert "--repository" in called_args
    assert "testpypi" in called_args