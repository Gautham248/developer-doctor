from datetime import datetime, timezone

from doctor.capabilities import Capability
from doctor.models import Finding, PluginResult, Status
from doctor.plugins.base import DoctorPlugin
from doctor.services.process_service import ProcessService
from doctor.utils.state import load_state, save_state

STATE_KEY = "ai_ide"

IDE_PROCESS_PATTERNS: dict[str, list[str]] = {
    "Antigravity": ["antigravity"],
    "VS Code": ["code helper", "visual studio code"],
    "Cursor": ["cursor helper", "cursor"],
    "Claude Code": ["claude"],
    "Gemini CLI": ["gemini"],
}

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
    capabilities = [Capability.PROCESS_INSPECTION]

    def run(self) -> PluginResult:
        try:
            process_service = self.use_service(ProcessService)
            families = process_service.sample_grouped(self._match_ide_family)

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
        lowered = process_name.lower()
        for family, patterns in IDE_PROCESS_PATTERNS.items():
            for pattern in patterns:
                if pattern in lowered:
                    return family
        return None