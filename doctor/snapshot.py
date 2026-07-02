import re
from datetime import datetime, timedelta, timezone

from pydantic import BaseModel

from doctor.models import Report
from doctor.utils.state import load_json, save_json

SNAPSHOTS_KEY = "snapshots"
MAX_SNAPSHOTS = 90  # ~3 months of daily snapshots, keeps state file bounded


class Snapshot(BaseModel):
    captured_at: datetime
    report: Report


def save_snapshot(report: Report) -> None:
    """Append the given report as a new historical snapshot (§17).

    Snapshots are capped at MAX_SNAPSHOTS, oldest dropped first, so the
    state file doesn't grow unbounded over months of daily use.
    """
    snapshots = load_snapshots()
    snapshots.append(Snapshot(captured_at=datetime.now(timezone.utc), report=report))
    snapshots.sort(key=lambda s: s.captured_at)
    if len(snapshots) > MAX_SNAPSHOTS:
        snapshots = snapshots[-MAX_SNAPSHOTS:]
    save_json(SNAPSHOTS_KEY, [s.model_dump(mode="json") for s in snapshots])


def load_snapshots() -> list[Snapshot]:
    """Load all stored snapshots, oldest first. Never raises — corrupted
    or missing state returns an empty list, and any individual snapshot
    that no longer matches the schema (e.g. saved by an older doctor
    version) is silently skipped rather than failing the whole load."""
    data = load_json(SNAPSHOTS_KEY)
    if not isinstance(data, list):
        return []
    snapshots = []
    for item in data:
        try:
            snapshots.append(Snapshot.model_validate(item))
        except Exception:
            continue
    snapshots.sort(key=lambda s: s.captured_at)
    return snapshots


def find_closest_snapshot(target_time: datetime, snapshots: list[Snapshot]) -> Snapshot | None:
    """Return the snapshot whose captured_at is closest to target_time."""
    if not snapshots:
        return None
    return min(snapshots, key=lambda s: abs((s.captured_at - target_time).total_seconds()))


RELATIVE_DAYS_PATTERN = re.compile(r"^(\d+)d$")


def parse_time_spec(spec: str) -> datetime | None:
    """Parse a `doctor diff <target>` argument into a UTC datetime.

    Supports "today", "yesterday", "Nd" (N days ago, e.g. "7d"), or an
    ISO 8601 date/datetime string. Returns None if unparseable, rather
    than raising — the CLI reports a clear error instead of a traceback.
    """
    now = datetime.now(timezone.utc)
    normalized = spec.strip().lower()

    if normalized == "today":
        return now
    if normalized == "yesterday":
        return now - timedelta(days=1)

    match = RELATIVE_DAYS_PATTERN.match(normalized)
    if match:
        return now - timedelta(days=int(match.group(1)))

    try:
        parsed = datetime.fromisoformat(spec)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except ValueError:
        return None