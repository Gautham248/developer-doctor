from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from doctor.models import PluginResult, Report, Status
from doctor.snapshot import (
    Snapshot,
    find_closest_snapshot,
    load_snapshots,
    parse_time_spec,
    save_snapshot,
)


def _report(score: int = 100) -> Report:
    return Report(score=score, results=[PluginResult(plugin_name="cpu", status=Status.PASS)])


def test_save_and_load_snapshot_roundtrip(tmp_path: Path):
    with patch("doctor.utils.state._state_dir", return_value=tmp_path):
        save_snapshot(_report(95))
        snapshots = load_snapshots()

    assert len(snapshots) == 1
    assert snapshots[0].report.score == 95


def test_load_snapshots_returns_empty_list_when_missing(tmp_path: Path):
    with patch("doctor.utils.state._state_dir", return_value=tmp_path):
        assert load_snapshots() == []


def test_save_snapshot_caps_at_max(tmp_path: Path):
    with (
        patch("doctor.utils.state._state_dir", return_value=tmp_path),
        patch("doctor.snapshot.MAX_SNAPSHOTS", 2),
    ):
        save_snapshot(_report(90))
        save_snapshot(_report(91))
        save_snapshot(_report(92))
        snapshots = load_snapshots()

    assert len(snapshots) == 2
    assert [s.report.score for s in snapshots] == [91, 92]


def test_find_closest_snapshot_picks_nearest():
    now = datetime.now(timezone.utc)
    old = Snapshot(captured_at=now - timedelta(days=10), report=_report(80))
    recent = Snapshot(captured_at=now - timedelta(days=1), report=_report(95))
    target = now - timedelta(days=2)

    assert find_closest_snapshot(target, [old, recent]) is recent


def test_find_closest_snapshot_returns_none_for_empty_list():
    assert find_closest_snapshot(datetime.now(timezone.utc), []) is None


def test_parse_time_spec_yesterday():
    now = datetime.now(timezone.utc)
    parsed = parse_time_spec("yesterday")
    assert parsed is not None
    assert abs((now - parsed).total_seconds() - 86400) < 5


def test_parse_time_spec_relative_days():
    now = datetime.now(timezone.utc)
    parsed = parse_time_spec("7d")
    assert parsed is not None
    assert abs((now - parsed).total_seconds() - 7 * 86400) < 5


def test_parse_time_spec_iso_date():
    parsed = parse_time_spec("2026-06-25")
    assert parsed is not None
    assert parsed.date().isoformat() == "2026-06-25"


def test_parse_time_spec_returns_none_on_garbage():
    assert parse_time_spec("not a date") is None