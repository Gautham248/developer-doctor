from doctor.models import Finding, PluginResult, Status
from doctor.scoring import compute_health_score, has_critical_failures


def _result(status: Status, score_delta: int = 0) -> PluginResult:
    return PluginResult(
        plugin_name="fake",
        status=status,
        score_delta=score_delta,
        findings=[Finding(summary="x")],
    )


def test_compute_health_score_starts_at_100_with_no_deductions():
    assert compute_health_score([_result(Status.PASS)]) == 100


def test_compute_health_score_deducts_correctly():
    results = [_result(Status.WARN, score_delta=5), _result(Status.FAIL, score_delta=15)]
    assert compute_health_score(results) == 80


def test_compute_health_score_never_goes_below_zero():
    results = [_result(Status.FAIL, score_delta=999)]
    assert compute_health_score(results) == 0


def test_has_critical_failures_true_when_any_fail_present():
    results = [_result(Status.PASS), _result(Status.WARN), _result(Status.FAIL)]
    assert has_critical_failures(results) is True


def test_has_critical_failures_false_with_only_warn_and_pass():
    results = [_result(Status.PASS), _result(Status.WARN)]
    assert has_critical_failures(results) is False


def test_has_critical_failures_false_with_empty_results():
    assert has_critical_failures([]) is False