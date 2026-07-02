from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from doctor.cli import app
from doctor.sdk.publish import PublishResult

runner = CliRunner()


def _fake_check_success(path: Path) -> PublishResult:
    return PublishResult(success=True, output="Checking: PASSED", dry_run=True)


def test_publish_aborts_without_confirmation(tmp_path: Path):
    with (
        patch("doctor.cli.check_package", side_effect=_fake_check_success),
        patch("doctor.cli.upload_package") as mock_upload,
    ):
        result = runner.invoke(app, ["plugin", "publish", str(tmp_path)], input="n\n")

    assert "Aborted" in result.stdout
    mock_upload.assert_not_called()


def test_publish_uploads_with_yes_flag(tmp_path: Path):
    with (
        patch("doctor.cli.check_package", side_effect=_fake_check_success),
        patch(
            "doctor.cli.upload_package",
            return_value=PublishResult(success=True, output="Uploaded", dry_run=False),
        ) as mock_upload,
    ):
        result = runner.invoke(app, ["plugin", "publish", str(tmp_path), "--yes"])

    assert result.exit_code == 0
    mock_upload.assert_called_once()


def test_publish_stops_if_check_fails(tmp_path: Path):
    with (
        patch(
            "doctor.cli.check_package",
            return_value=PublishResult(success=False, output="bad package", dry_run=True),
        ),
        patch("doctor.cli.upload_package") as mock_upload,
    ):
        result = runner.invoke(app, ["plugin", "publish", str(tmp_path)])

    assert result.exit_code == 1
    mock_upload.assert_not_called()