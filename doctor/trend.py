from dataclasses import dataclass
from datetime import datetime

from doctor.snapshot import Snapshot

MIN_SNAPSHOTS_FOR_TREND = 3
MIN_PERCENT_CHANGE_TO_REPORT = 5.0


@dataclass
class MetricTrend:
    plugin_name: str
    metric_key: str
    first_value: float
    last_value: float
    first_seen: datetime
    last_seen: datetime
    num_points: int

    @property
    def percent_change(self) -> float | None:
        if self.first_value == 0:
            return None
        return ((self.last_value - self.first_value) / abs(self.first_value)) * 100

    @property
    def direction(self) -> str:
        if self.last_value > self.first_value:
            return "up"
        if self.last_value < self.first_value:
            return "down"
        return "flat"


def compute_trends(snapshots: list[Snapshot]) -> list[MetricTrend]:
    """Surface trends across a series of historical snapshots (§17) —
    distinct from a simple two-point diff, this requires at least
    MIN_SNAPSHOTS_FOR_TREND data points for a given plugin+metric before
    reporting anything.

    Honest limitation: this compares the earliest and latest recorded
    values for each metric, not a fitted regression line. It's simpler
    than true trend detection, but the >=3-point requirement and the
    reported time span are what distinguish it from a plain diff, which
    only ever looks at two points.

    Known gap: only flat numeric metadata fields are tracked. Nested
    structures (e.g. ai_ide's per-family dict) aren't flattened into
    trackable metrics yet.
    """
    if len(snapshots) < MIN_SNAPSHOTS_FOR_TREND:
        return []

    series: dict[tuple[str, str], list[tuple[datetime, float]]] = {}

    for snap in snapshots:
        for result in snap.report.results:
            for key, value in result.metadata.items():
                if isinstance(value, bool) or not isinstance(value, int | float):
                    continue
                series.setdefault((result.plugin_name, key), []).append(
                    (snap.captured_at, float(value))
                )

    trends = []
    for (plugin_name, key), points in series.items():
        if len(points) < MIN_SNAPSHOTS_FOR_TREND:
            continue
        points.sort(key=lambda p: p[0])
        first_time, first_value = points[0]
        last_time, last_value = points[-1]

        trend = MetricTrend(
            plugin_name=plugin_name,
            metric_key=key,
            first_value=first_value,
            last_value=last_value,
            first_seen=first_time,
            last_seen=last_time,
            num_points=len(points),
        )

        pct = trend.percent_change
        if pct is not None and abs(pct) < MIN_PERCENT_CHANGE_TO_REPORT:
            continue

        trends.append(trend)

    trends.sort(key=lambda t: (t.plugin_name, t.metric_key))
    return trends