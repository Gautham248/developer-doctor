"""Memory optimizer service.

Mirrors ThermalOptimizer's process-category patterns and quit/kill
mechanics, but ranks and scopes actions by RAM (RSS) instead of CPU%.

Kill-safety itself is NOT reclassified here — MemoryProcess already
carries it (ProcessService.sample_memory_processes() calls the same
ThermalService._classify_kill_safety() thermal targets use). This
service only decides which *action* applies (quit app / SIGTERM /
suggestion-only background service), reusing the exact name-pattern
sets ThermalOptimizer already maintains rather than re-authoring them
— the categories (auto-updater, analytics daemon, cloud sync,
indexing daemon) are about what a process *is*, not which resource
flagged it, so they apply equally to a CPU-heavy or RAM-heavy finding.

Actual process termination is delegated to ThermalOptimizer, whose
quit_app_gracefully()/terminate_process() already only need a pid or
app name — nothing CPU-specific about them.
"""

from __future__ import annotations

from dataclasses import dataclass

from doctor.services.process_service import MemoryProcess
from doctor.services.thermal_service import KillSafety
from doctor.services.thermal_optimizer import (
    OptimizationAction,
    ThermalOptimizer,
    _ANALYTICS_NAMES,
    _BACKGROUND_FETCH_NAMES,
    _CLOUD_SYNC_PATTERNS,
    _INDEXING_NAMES,
    _INDEXING_PREFIXES,
    _UPDATER_PATTERNS,
    _WELL_KNOWN_APPS,
)

_matches_any = ThermalOptimizer._matches_any


@dataclass
class MemoryOptimizationTarget:
    display_name: str
    rss_gb: float
    action: OptimizationAction
    reason: str
    pid: int
    app_name: str | None = None
    suggestion_text: str = ""


class MemoryOptimizer:
    """Scan RSS-ranked processes and propose safe close/quit actions."""

    def __init__(self) -> None:
        self._executor = ThermalOptimizer()

    # -- Public API -----------------------------------------------------

    def scan(self, processes: list[MemoryProcess]) -> list[MemoryOptimizationTarget]:
        """Return a prioritized list of optimization targets, sorted by
        RSS descending. SUGGESTION_ONLY targets always appear last,
        regardless of RSS, matching ThermalOptimizer's convention."""
        actionable: list[MemoryOptimizationTarget] = []
        suggestions: list[MemoryOptimizationTarget] = []

        for proc in processes:
            if proc.kill_safety == KillSafety.UNSAFE:
                continue

            target = self._classify(proc)
            if target is None:
                continue

            if target.action == OptimizationAction.SUGGESTION_ONLY:
                suggestions.append(target)
            else:
                actionable.append(target)

        actionable.sort(key=lambda t: t.rss_gb, reverse=True)
        suggestions.sort(key=lambda t: t.rss_gb, reverse=True)
        return actionable + suggestions

    def quit_app_gracefully(self, app_name: str) -> bool:
        return self._executor.quit_app_gracefully(app_name)

    def terminate_process(self, pid: int, force: bool = False) -> bool:
        return self._executor.terminate_process(pid, force=force)

    # -- Classification ---------------------------------------------------

    def _classify(self, proc: MemoryProcess) -> MemoryOptimizationTarget | None:
        name = proc.name

        if name in _INDEXING_NAMES or any(name.startswith(p) for p in _INDEXING_PREFIXES):
            return MemoryOptimizationTarget(
                display_name=name,
                rss_gb=proc.rss_gb,
                action=OptimizationAction.SUGGESTION_ONLY,
                reason="Spotlight indexing daemon",
                pid=proc.pid,
                suggestion_text=(
                    "Run `sudo mdutil -a -i off` to pause Spotlight indexing "
                    "(re-enable with `sudo mdutil -a -i on`)."
                ),
            )

        if _matches_any(name, _CLOUD_SYNC_PATTERNS):
            return MemoryOptimizationTarget(
                display_name=name,
                rss_gb=proc.rss_gb,
                action=OptimizationAction.SUGGESTION_ONLY,
                reason="Cloud sync daemon — pausing may risk data loss",
                pid=proc.pid,
                suggestion_text=(
                    f"Pause '{name}' manually via its menu bar icon or "
                    "System Settings to avoid data loss."
                ),
            )

        if name in _ANALYTICS_NAMES:
            return MemoryOptimizationTarget(
                display_name=name,
                rss_gb=proc.rss_gb,
                action=OptimizationAction.SIGTERM_PROCESS,
                reason="Crash reporter / analytics daemon",
                pid=proc.pid,
            )

        if name in _BACKGROUND_FETCH_NAMES:
            return MemoryOptimizationTarget(
                display_name=name,
                rss_gb=proc.rss_gb,
                action=OptimizationAction.SIGTERM_PROCESS,
                reason="Background indexing / fetch daemon",
                pid=proc.pid,
            )

        if _matches_any(name, _UPDATER_PATTERNS):
            return MemoryOptimizationTarget(
                display_name=name,
                rss_gb=proc.rss_gb,
                action=OptimizationAction.SIGTERM_PROCESS,
                reason="Background software updater",
                pid=proc.pid,
            )

        # Everything else already passed the RSS threshold
        # (ProcessService.sample_memory_processes) and isn't UNSAFE —
        # treat it as a normal user app/process to offer to close.
        app_name = _WELL_KNOWN_APPS.get(name)
        action = (
            OptimizationAction.QUIT_APP if app_name else OptimizationAction.SIGTERM_PROCESS
        )
        reason = f"Using {proc.rss_gb:.1f} GB of RAM"
        if proc.kill_safety != KillSafety.SAFE:
            reason += f" — {proc.kill_reason}"

        return MemoryOptimizationTarget(
            display_name=app_name or name,
            rss_gb=proc.rss_gb,
            action=action,
            reason=reason,
            pid=proc.pid,
            app_name=app_name,
        )
