from datetime import datetime, timedelta, timezone

from doctor.models import PluginResult, Report, Status
from doctor.snapshot import Snapshot
from doctor.trend import compute_trends


def _snapshot(days_ago: int, disk_percent: float, cpu_percent: float = 10.0) -> Snapshot:
    now = datetime.now(timezone.utc)
    report = Report(
        score=100,
        results=[
            PluginResult(plugin_name="disk", status=Status.PASS, metadata={"percent": disk_percent}),
            PluginResult(plugin_name="cpu", status=Status.PASS, metadata={"cpu_percent": cpu_percent}),
        ],
    )
    return Snapshot(captured_at=now - timedelta(days=days_ago), report=report)


def test_compute_trends_empty_below_minimum_snapshots():
    snapshots = [_snapshot(2, 40.0), _snapshot(1, 42.0)]
    assert compute_trends(snapshots) == []


def test_compute_trends_detects_growth_above_threshold():
    snapshots = [_snapshot(20, 40.0), _snapshot(10, 48.0), _snapshot(0, 55.0)]
    trends = compute_trends(snapshots)

    disk_trend = next(t for t in trends if t.metric_key == "percent")
    assert disk_trend.plugin_name == "disk"
    assert disk_trend.direction == "up"
    assert disk_trend.percent_change is not None
    assert disk_trend.percent_change > 30


def test_compute_trends_filters_noise_below_threshold():
    snapshots = [_snapshot(20, 40.0, 10.0), _snapshot(10, 40.5, 10.1), _snapshot(0, 41.0, 10.2)]
    assert compute_trends(snapshots) == []


def test_compute_trends_ignores_non_numeric_metadata():
    now = datetime.now(timezone.utc)
    snapshots = []
    for i in range(3):
        report = Report(
            score=100,
            results=[
                PluginResult(
                    plugin_name="git",
                    status=Status.PASS,
                    metadata={"global_name": "Gautham", "remote_host": "github.com"},
                )
            ],
        )
        snapshots.append(Snapshot(captured_at=now - timedelta(days=2 - i), report=report))

    assert compute_trends(snapshots) == []


def test_compute_trends_requires_min_points_per_metric():
    now = datetime.now(timezone.utc)
    snapshots = [
        Snapshot(
            captured_at=now - timedelta(days=2),
            report=Report(
                score=100,
                results=[PluginResult(plugin_name="disk", status=Status.PASS, metadata={"percent": 40.0})],
            ),
        ),
        Snapshot(
            captured_at=now - timedelta(days=1),
            report=Report(score=100, results=[]),
        ),
        Snapshot(
            captured_at=now,
            report=Report(
                score=100,
                results=[PluginResult(plugin_name="disk", status=Status.PASS, metadata={"percent": 60.0})],
            ),
        ),
    ]

    assert compute_trends(snapshots) == []