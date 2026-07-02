from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from doctor.models import Status
from doctor.plugins.ai_ide import AIIDEPlugin

PATCH_TARGET = "doctor.services.process_service.ProcessService.sample_grouped"


def test_match_ide_family_antigravity():
    plugin = AIIDEPlugin()
    assert plugin._match_ide_family("Antigravity IDE Helper (Renderer)") == "Antigravity"


def test_match_ide_family_vscode():
    plugin = AIIDEPlugin()
    assert plugin._match_ide_family("Code Helper (Plugin)") == "VS Code"


def test_match_ide_family_unmatched():
    plugin = AIIDEPlugin()
    assert plugin._match_ide_family("Finder") is None


def test_ai_ide_plugin_passes_with_no_processes():
    plugin = AIIDEPlugin()
    with patch(PATCH_TARGET, return_value={}):
        result = plugin.run()

    assert result.status == Status.PASS
    assert "No AI IDE processes detected" in result.findings[0].summary


def test_ai_ide_plugin_passes_under_normal_usage():
    plugin = AIIDEPlugin()
    families = {"VS Code": {"cpu_percent": 10.0, "ram_gb": 1.0, "process_count": 3.0}}
    with (
        patch(PATCH_TARGET, return_value=families),
        patch("doctor.plugins.ai_ide.load_state", return_value={}),
        patch("doctor.plugins.ai_ide.save_state"),
    ):
        result = plugin.run()

    assert result.status == Status.PASS
    assert result.score_delta == 0


def test_ai_ide_plugin_fails_on_excessive_ram():
    plugin = AIIDEPlugin()
    families = {"Cursor": {"cpu_percent": 5.0, "ram_gb": 10.0, "process_count": 4.0}}
    with (
        patch(PATCH_TARGET, return_value=families),
        patch("doctor.plugins.ai_ide.load_state", return_value={}),
        patch("doctor.plugins.ai_ide.save_state"),
    ):
        result = plugin.run()

    assert result.status == Status.FAIL
    assert result.score_delta == 15


def test_ai_ide_plugin_warns_on_newly_elevated_cpu():
    plugin = AIIDEPlugin()
    families = {"Antigravity": {"cpu_percent": 90.0, "ram_gb": 1.0, "process_count": 2.0}}
    with (
        patch(PATCH_TARGET, return_value=families),
        patch("doctor.plugins.ai_ide.load_state", return_value={}),
        patch("doctor.plugins.ai_ide.save_state") as mock_save,
    ):
        result = plugin.run()

    assert result.status == Status.PASS
    mock_save.assert_called_once()
    saved_state = mock_save.call_args[0][1]
    assert "Antigravity" in saved_state


def test_ai_ide_plugin_warns_after_sustained_cpu():
    plugin = AIIDEPlugin()
    families = {"Antigravity": {"cpu_percent": 90.0, "ram_gb": 1.0, "process_count": 2.0}}
    first_seen = (datetime.now(timezone.utc) - timedelta(minutes=20)).isoformat()
    with (
        patch(PATCH_TARGET, return_value=families),
        patch("doctor.plugins.ai_ide.load_state", return_value={"Antigravity": first_seen}),
        patch("doctor.plugins.ai_ide.save_state"),
    ):
        result = plugin.run()

    assert result.status == Status.WARN
    assert any("20 minutes" in f.summary for f in result.findings)


def test_ai_ide_plugin_fails_after_very_sustained_cpu():
    plugin = AIIDEPlugin()
    families = {"Antigravity": {"cpu_percent": 95.0, "ram_gb": 1.0, "process_count": 2.0}}
    first_seen = (datetime.now(timezone.utc) - timedelta(minutes=45)).isoformat()
    with (
        patch(PATCH_TARGET, return_value=families),
        patch("doctor.plugins.ai_ide.load_state", return_value={"Antigravity": first_seen}),
        patch("doctor.plugins.ai_ide.save_state"),
    ):
        result = plugin.run()

    assert result.status == Status.FAIL
    assert any("over 45 minutes" in f.summary for f in result.findings)


def test_ai_ide_plugin_clears_state_when_no_longer_elevated():
    plugin = AIIDEPlugin()
    families = {"Antigravity": {"cpu_percent": 5.0, "ram_gb": 0.5, "process_count": 2.0}}
    old_first_seen = (datetime.now(timezone.utc) - timedelta(minutes=60)).isoformat()
    with (
        patch(PATCH_TARGET, return_value=families),
        patch("doctor.plugins.ai_ide.load_state", return_value={"Antigravity": old_first_seen}),
        patch("doctor.plugins.ai_ide.save_state") as mock_save,
    ):
        result = plugin.run()

    assert result.status == Status.PASS
    saved_state = mock_save.call_args[0][1]
    assert "Antigravity" not in saved_state


def test_ai_ide_plugin_never_raises_on_unexpected_failure():
    plugin = AIIDEPlugin()
    with patch(PATCH_TARGET, side_effect=RuntimeError("boom")):
        result = plugin.run()

    assert result.status == Status.FAIL
    assert "Could not run AI IDE diagnostics" in result.findings[0].summary