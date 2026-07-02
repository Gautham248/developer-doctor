from pathlib import Path
from unittest.mock import MagicMock, patch

from doctor.sdk.lint import lint_plugin


def test_lint_plugin_skips_tools_not_installed(tmp_path: Path):
    with patch("shutil.which", return_value=None):
        result = lint_plugin(tmp_path)

    assert result.passed is True
    assert all(not r.ran for r in result.results)


def test_lint_plugin_passes_when_tools_succeed(tmp_path: Path):
    mock_result = MagicMock(returncode=0, stdout="", stderr="")
    with (
        patch("shutil.which", return_value="/usr/bin/tool"),
        patch("subprocess.run", return_value=mock_result),
    ):
        result = lint_plugin(tmp_path)

    assert result.passed is True
    assert all(r.ran and r.passed for r in result.results)


def test_lint_plugin_fails_when_a_tool_reports_issues(tmp_path: Path):
    def fake_run(command, **kwargs):
        if command[0] == "ruff":
            return MagicMock(returncode=1, stdout="some issue", stderr="")
        return MagicMock(returncode=0, stdout="", stderr="")

    with (
        patch("shutil.which", return_value="/usr/bin/tool"),
        patch("subprocess.run", side_effect=fake_run),
    ):
        result = lint_plugin(tmp_path)

    assert result.passed is False
    ruff_result = next(r for r in result.results if r.tool == "ruff")
    assert ruff_result.passed is False