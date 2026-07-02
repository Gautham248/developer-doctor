from pathlib import Path
from unittest.mock import patch

from doctor.baseline import diff_reports, load_baseline, save_baseline
from doctor.models import  PluginResult, Report, Status


def _report(score: int, results: list[PluginResult]) -> Report:
    return Report(score=score, results=results)


def test_baseline_roundtrip(tmp_path: Path):
    report = _report(95, [PluginResult(plugin_name="cpu", status=Status.PASS, metadata={"cpu_percent": 10.0})])
    with patch("doctor.utils.state._state_dir", return_value=tmp_path):
        save_baseline(report)
        loaded = load_baseline()

    assert loaded is not None
    assert loaded.score == 95
    assert loaded.results[0].plugin_name == "cpu"
    assert loaded.results[0].metadata["cpu_percent"] == 10.0


def test_load_baseline_returns_none_when_missing(tmp_path: Path):
    with patch("doctor.utils.state._state_dir", return_value=tmp_path):
        assert load_baseline() is None


def test_load_baseline_returns_none_on_corrupted_data(tmp_path: Path):
    (tmp_path / "baseline.json").write_text('{"not": "a valid report"}')
    with patch("doctor.utils.state._state_dir", return_value=tmp_path):
        assert load_baseline() is None


def test_diff_reports_no_changes():
    baseline = _report(
        95, [PluginResult(plugin_name="cpu", status=Status.PASS, metadata={"cpu_percent": 10.0})]
    )
    current = _report(
        95, [PluginResult(plugin_name="cpu", status=Status.PASS, metadata={"cpu_percent": 10.0})]
    )
    diffs = diff_reports(baseline, current)

    assert len(diffs) == 1
    assert diffs[0].has_changes is False


def test_diff_reports_detects_status_change():
    baseline = _report(95, [PluginResult(plugin_name="cpu", status=Status.PASS)])
    current = _report(80, [PluginResult(plugin_name="cpu", status=Status.FAIL)])
    diffs = diff_reports(baseline, current)

    assert diffs[0].status_changed is True
    assert diffs[0].baseline_status == "PASS"
    assert diffs[0].current_status == "FAIL"


def test_diff_reports_detects_metadata_change():
    baseline = _report(
        95, [PluginResult(plugin_name="disk", status=Status.PASS, metadata={"percent": 10.0})]
    )
    current = _report(
        90, [PluginResult(plugin_name="disk", status=Status.PASS, metadata={"percent": 45.0})]
    )
    diffs = diff_reports(baseline, current)

    assert diffs[0].status_changed is False
    assert diffs[0].changed_metadata == {"percent": (10.0, 45.0)}


def test_diff_reports_handles_plugin_missing_from_current():
    baseline = _report(95, [PluginResult(plugin_name="docker", status=Status.PASS)])
    current = _report(95, [])
    diffs = diff_reports(baseline, current)

    assert diffs[0].plugin_name == "docker"
    assert diffs[0].baseline_status == "PASS"
    assert diffs[0].current_status is None
    assert diffs[0].status_changed is True


def test_diff_reports_handles_plugin_new_in_current():
    baseline = _report(95, [])
    current = _report(95, [PluginResult(plugin_name="docker", status=Status.WARN)])
    diffs = diff_reports(baseline, current)

    assert diffs[0].plugin_name == "docker"
    assert diffs[0].baseline_status is None
    assert diffs[0].current_status == "WARN"