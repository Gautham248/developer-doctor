from doctor.models import PluginResult, Status

STARTING_SCORE = 100


def compute_health_score(results: list[PluginResult]) -> int:
    """Aggregate plugin score deltas into a single health score.

    Score starts at 100 (PRD §9) and is never allowed below 0, even if
    deductions overshoot.
    """
    total_deductions = sum(result.score_delta for result in results)
    return max(0, STARTING_SCORE - total_deductions)


def has_critical_failures(results: list[PluginResult]) -> bool:
    """True if any plugin result is FAIL — the signal §18 CI mode uses
    to decide whether to exit non-zero."""
    return any(result.status == Status.FAIL for result in results)