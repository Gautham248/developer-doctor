from doctor.models import PluginResult

STARTING_SCORE = 100


def compute_health_score(results: list[PluginResult]) -> int:
    """Aggregate plugin score deltas into a single health score.

    Score starts at 100 (PRD §9) and is never allowed below 0, even if
    deductions overshoot.
    """
    total_deductions = sum(result.score_delta for result in results)
    return max(0, STARTING_SCORE - total_deductions)