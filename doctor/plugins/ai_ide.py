import time
from datetime import datetime, timezone

import psutil

from doctor.models import Finding, PluginResult, Status
from doctor.plugins.base import DoctorPlugin
from doctor.utils.state import load_state, save_state

STATE_KEY = "ai_ide"

# Best-effort, case-insensitive substring match against psutil's process name.
#
# Electron IDEs (Antigravity, VS Code, Cursor) spawn clearly-named helper
# processes, which is what makes reliable detection possible. CLI-based
# agents (Claude Code, Gemini CLI) are matched on much weaker substrings
# ("claude", "gemini") that could collide with unrelated processes — a
# known limitation, not a confident match, flagged here rather than hidden.
IDE_PROCESS_PATTERNS: dict[str, list[str]] = {
    "Antigravity": ["antigravity"],
    "VS Code": ["code helper", "visual studio code"],
    "Cursor": ["cursor helper", "cursor"],
    "Claude Code": ["claude"],
    "Gemini CLI": ["gemini"],
}

SAMPLE_INTERVAL_SECONDS = 0.5

SUSTAINED_CPU_PERCENT_THRESHOLD = 50.0
SUSTAINED_DURATION_WARN_MINUTES = 15.0
SUSTAINED_DURATION_FAIL_MINUTES = 40.0

RAM_WARN_GB = 4.0
RAM_FAIL_GB = 8.0

WARN_SCORE_DELTA = 5
FAIL_SCORE_DELTA = 15


class AIIDEPlugin(DoctorPlugin):
    name = "ai_ide"
    description = (
        "Detects orphaned or runaway AI IDE processes (Antigravity, VS Code, "
        "Cursor, Claude Code, Gemini CLI) and flags sustained high CPU or "
        "excessive RAM usage."
    )

    def run(self) -> PluginResult:
        try:
            families = self._sample_ide_families()

            if not families:
                return PluginResult(
                    plugin_name=self.name,
                    status=Status.PASS,
                    findings=[Finding(summary="No AI IDE processes detected")],
                )

            state = load_state(STATE_KEY)
            now = datetime.now(timezone.utc)

            findings: list[Finding] = []
            recommendations: list[str] = []
            status = Status.PASS
            score_delta = 0
            new_state: dict[str, str] = {}

            for family_name, stats in sorted(families.items()):
                cpu_percent = stats["cpu_percent"]
                ram_gb = stats["ram_gb"]
                process_count = int(stats["process_count"])

                findings.append(
                    Finding(
                        summary=f"{family_name}: {cpu_percent:.0f}% CPU, {ram_gb:.1f} GB RAM "
                        f"({process_count} process{'es' if process_count != 1 else ''})"
                    )
                )

                if ram_gb >= RAM_FAIL_GB:
                    status = Status.FAIL
                    score_delta = max(score_delta, FAIL_SCORE_DELTA)
                    recommendations.append(
                        f"{family_name} is using {ram_gb:.1f} GB of RAM. Consider restarting it."
                    )
                elif ram_gb >= RAM_WARN_GB:
                    if status == Status.PASS:
                        status = Status.WARN
                    score_delta = max(score_delta, WARN_SCORE_DELTA)
                    recommendations.append(
                        f"{family_name} is using a notable amount of RAM ({ram_gb:.1f} GB)."
                    )

                # Only families currently over the CPU threshold get carried
                # into new_state — anything not elevated this run simply
                # isn't written back, which resets its "first seen" clock
                # for the next time it spikes.
                if cpu_percent >= SUSTAINED_CPU_PERCENT_THRESHOLD:
                    first_seen_str = state.get(family_name)
                    try:
                        first_seen = (
                            datetime.fromisoformat(first_seen_str) if first_seen_str else now
                        )
                    except ValueError:
                        first_seen = now

                    elapsed_minutes = (now - first_seen).total_seconds() / 60.0
                    new_state[family_name] = first_seen.isoformat()

                    if elapsed_minutes >= SUSTAINED_DURATION_FAIL_MINUTES:
                        status = Status.FAIL
                        score_delta = max(score_delta, FAIL_SCORE_DELTA)
                        findings.append(
                            Finding(
                                summary=f"{family_name} has been using {cpu_percent:.0f}% CPU "
                                f"for over {int(elapsed_minutes)} minutes"
                            )
                        )
                        recommendations.append(
                            f"{family_name} has been pinning the CPU for a long time. Likely "
                            f"causes: stuck indexing, a corrupted index, or a language-server "
                            f"bug. Try restarting {family_name}."
                        )
                    elif elapsed_minutes >= SUSTAINED_DURATION_WARN_MINUTES:
                        if status == Status.PASS:
                            status = Status.WARN
                        score_delta = max(score_delta, WARN_SCORE_DELTA)
                        findings.append(
                            Finding(
                                summary=f"{family_name} has been using {cpu_percent:.0f}% CPU "
                                f"for {int(elapsed_minutes)} minutes"
                            )
                        )

            save_state(STATE_KEY, new_state)

            return PluginResult(
                plugin_name=self.name,
                status=status,
                score_delta=score_delta,
                findings=findings,
                recommendations=recommendations,
                metadata={"families": families},
            )
        except Exception as e:
            return PluginResult(
                plugin_name=self.name,
                status=Status.FAIL,
                findings=[Finding(summary="Could not run AI IDE diagnostics", detail=str(e))],
            )

    def _match_ide_family(self, process_name: str) -> str | None:
        """Return the IDE family a process belongs to, or None if unmatched."""
        lowered = process_name.lower()
        for family, patterns in IDE_PROCESS_PATTERNS.items():
            for pattern in patterns:
                if pattern in lowered:
                    return family
        return None

    def _sample_ide_families(self) -> dict[str, dict[str, float]]:
        """Aggregate CPU%/RAM/process-count per matched IDE family.

        Uses the same prime-then-sample technique as CPUPlugin, since
        psutil returns a misleading 0.0% on the first per-process
        cpu_percent() call.
        """
        matched_procs = []
        for proc in psutil.process_iter(["name"]):
            try:
                name = proc.info["name"]
                if name and self._match_ide_family(name):
                    proc.cpu_percent(interval=None)  # prime
                    matched_procs.append(proc)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        if not matched_procs:
            return {}

        time.sleep(SAMPLE_INTERVAL_SECONDS)

        families: dict[str, dict[str, float]] = {}
        for proc in matched_procs:
            try:
                name = proc.name()
                family = self._match_ide_family(name)
                if not family:
                    continue
                cpu = proc.cpu_percent(interval=None)
                ram_gb = proc.memory_info().rss / (1024**3)

                if family not in families:
                    families[family] = {"cpu_percent": 0.0, "ram_gb": 0.0, "process_count": 0.0}
                families[family]["cpu_percent"] += cpu
                families[family]["ram_gb"] += ram_gb
                families[family]["process_count"] += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        return families