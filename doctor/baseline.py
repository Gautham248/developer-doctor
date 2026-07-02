from dataclasses import dataclass, field
from typing import Any

from doctor.models import Report
from doctor.utils.state import load_json, save_json

BASELINE_KEY = "baseline"


def save_baseline(report: Report) -> None:
    """Persist the given report as the baseline snapshot (§16)."""
    save_json(BASELINE_KEY, report.model_dump(mode="json"))


def load_baseline() -> Report | None:
    """Load the previously saved baseline, or None if none exists, is
    corrupted, or no longer matches the Report schema (e.g. saved by an
    older doctor version) — never raises."""
    data = load_json(BASELINE_KEY)
    if data is None:
        return None
    try:
        return Report.model_validate(data)
    except Exception:
        return None


@dataclass
class PluginDiff:
    plugin_name: str
    baseline_status: str | None
    current_status: str | None
    changed_metadata: dict[str, tuple[Any, Any]] = field(default_factory=dict)

    @property
    def status_changed(self) -> bool:
        return self.baseline_status != self.current_status

    @property
    def has_changes(self) -> bool:
        return self.status_changed or bool(self.changed_metadata)


def diff_reports(baseline: Report, current: Report) -> list[PluginDiff]:
    """Compare a baseline Report against a current Report, per plugin.

    Plugins present in only one of the two reports (e.g. disabled via
    doctor.toml since the baseline was captured, or a new plugin
    installed since) still appear in the diff, with the missing side
    reported as None — a plugin disappearing or appearing is itself
    meaningful information, not something to silently drop.
    """
    baseline_by_name = {r.plugin_name: r for r in baseline.results}
    current_by_name = {r.plugin_name: r for r in current.results}
    all_names = sorted(set(baseline_by_name) | set(current_by_name))

    diffs = []
    for name in all_names:
        b = baseline_by_name.get(name)
        c = current_by_name.get(name)

        changed_metadata: dict[str, tuple[Any, Any]] = {}
        if b is not None and c is not None:
            all_keys = set(b.metadata) | set(c.metadata)
            for key in sorted(all_keys):
                old_val = b.metadata.get(key)
                new_val = c.metadata.get(key)
                if old_val != new_val:
                    changed_metadata[key] = (old_val, new_val)

        diffs.append(
            PluginDiff(
                plugin_name=name,
                baseline_status=b.status.value if b else None,
                current_status=c.status.value if c else None,
                changed_metadata=changed_metadata,
            )
        )
    return diffs