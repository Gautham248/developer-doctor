from pathlib import Path
from unittest.mock import MagicMock, patch

from doctor.sdk.package import package_plugin


def test_package_plugin_fails_without_pyproject(tmp_path: Path):
    result = package_plugin(tmp_path)
    assert result.success is False
    assert "pyproject.toml" in result.output


def test_package_plugin_fails_without_uv(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
    with patch("shutil.which", return_value=None):
        result = package_plugin(tmp_path)

    assert result.success is False
    assert "uv" in result.output.lower()


def test_package_plugin_succeeds_and_lists_artifacts(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    (dist_dir / "x-0.1.0.whl").write_text("fake wheel")

    mock_result = MagicMock(returncode=0, stdout="Built x", stderr="")
    with (
        patch("shutil.which", return_value="/usr/bin/uv"),
        patch("subprocess.run", return_value=mock_result),
    ):
        result = package_plugin(tmp_path)

    assert result.success is True
    assert len(result.artifacts) == 1


def test_package_plugin_fails_on_build_error(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
    mock_result = MagicMock(returncode=1, stdout="", stderr="build broke")
    with (
        patch("shutil.which", return_value="/usr/bin/uv"),
        patch("subprocess.run", return_value=mock_result),
    ):
        result = package_plugin(tmp_path)

    assert result.success is False
    assert "build broke" in result.output