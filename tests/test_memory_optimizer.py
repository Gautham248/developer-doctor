"""Tests for MemoryOptimizer — process classification and action logic."""

from __future__ import annotations

from unittest.mock import patch

from doctor.services.memory_optimizer import MemoryOptimizer
from doctor.services.process_service import MemoryProcess
from doctor.services.thermal_optimizer import OptimizationAction
from doctor.services.thermal_service import KillSafety


def _proc(
    name: str,
    rss_gb: float = 2.0,
    username: str = "gautham",
    pid: int = 1000,
    kill_safety: KillSafety = KillSafety.SAFE,
) -> MemoryProcess:
    return MemoryProcess(
        pid=pid,
        name=name,
        rss_gb=rss_gb,
        username=username,
        ppid=1,
        kill_safety=kill_safety,
        kill_reason="user-owned process" if kill_safety == KillSafety.SAFE else "system",
    )


# ---------------------------------------------------------------------------
# Classification tests
# ---------------------------------------------------------------------------

def test_spotlight_mds_is_suggestion_only():
    optimizer = MemoryOptimizer()
    proc = _proc("mds_stores", kill_safety=KillSafety.CAUTION, username="root")
    result = optimizer._classify(proc)

    assert result is not None
    assert result.action == OptimizationAction.SUGGESTION_ONLY
    assert "mdutil" in result.suggestion_text


def test_cloud_sync_is_suggestion_only():
    optimizer = MemoryOptimizer()
    proc = _proc("bird", kill_safety=KillSafety.SAFE)
    result = optimizer._classify(proc)

    assert result is not None
    assert result.action == OptimizationAction.SUGGESTION_ONLY
    assert "data loss" in result.suggestion_text


def test_auto_updater_is_sigterm():
    optimizer = MemoryOptimizer()
    proc = _proc("SoftwareUpdateNotificationManager", rss_gb=0.8)
    result = optimizer._classify(proc)

    assert result is not None
    assert result.action == OptimizationAction.SIGTERM_PROCESS
    assert result.reason == "Background software updater"


def test_analytics_daemon_is_sigterm():
    optimizer = MemoryOptimizer()
    proc = _proc("DiagnosticReporter", rss_gb=0.3)
    result = optimizer._classify(proc)

    assert result is not None
    assert result.action == OptimizationAction.SIGTERM_PROCESS
    assert result.reason == "Crash reporter / analytics daemon"


def test_well_known_app_gets_quit_app_action():
    optimizer = MemoryOptimizer()
    proc = _proc("Xcode", rss_gb=4.5)
    result = optimizer._classify(proc)

    assert result is not None
    assert result.action == OptimizationAction.QUIT_APP
    assert result.app_name == "Xcode"
    assert "4.5 GB" in result.reason


def test_unknown_user_process_gets_sigterm_action():
    optimizer = MemoryOptimizer()
    proc = _proc("my_custom_script", rss_gb=1.2)
    result = optimizer._classify(proc)

    assert result is not None
    assert result.action == OptimizationAction.SIGTERM_PROCESS
    assert result.app_name is None


def test_caution_process_reason_includes_kill_reason():
    optimizer = MemoryOptimizer()
    proc = _proc(
        "some_daemon",
        rss_gb=0.6,
        kill_safety=KillSafety.CAUTION,
        pid=999,
    )
    result = optimizer._classify(proc)

    assert result is not None
    assert "system" in result.reason  # kill_reason set by _proc() for non-SAFE


def test_unsafe_process_is_excluded_from_scan():
    optimizer = MemoryOptimizer()
    procs = [_proc("kernel_task", kill_safety=KillSafety.UNSAFE, username="root")]

    results = optimizer.scan(procs)

    assert results == []


# ---------------------------------------------------------------------------
# scan() ordering tests
# ---------------------------------------------------------------------------

def test_scan_sorts_actionable_by_rss_descending():
    optimizer = MemoryOptimizer()
    procs = [
        _proc("small_app", rss_gb=0.5, pid=1),
        _proc("big_app", rss_gb=3.0, pid=2),
        _proc("mid_app", rss_gb=1.5, pid=3),
    ]

    results = optimizer.scan(procs)

    assert [r.pid for r in results] == [2, 3, 1]


def test_scan_puts_suggestions_after_actionable_regardless_of_rss():
    optimizer = MemoryOptimizer()
    procs = [
        _proc("bird", rss_gb=5.0, pid=1),  # cloud sync -> SUGGESTION_ONLY, huge RSS
        _proc("Xcode", rss_gb=0.5, pid=2),  # actionable, small RSS
    ]

    results = optimizer.scan(procs)

    assert [r.pid for r in results] == [2, 1]


# ---------------------------------------------------------------------------
# Execution delegation
# ---------------------------------------------------------------------------

def test_terminate_process_delegates_to_thermal_optimizer():
    optimizer = MemoryOptimizer()
    with patch(
        "doctor.services.thermal_optimizer.ThermalOptimizer.terminate_process",
        return_value=True,
    ) as mock_terminate:
        result = optimizer.terminate_process(1234, force=True)

    assert result is True
    mock_terminate.assert_called_once_with(1234, force=True)


def test_quit_app_gracefully_delegates_to_thermal_optimizer():
    optimizer = MemoryOptimizer()
    with patch(
        "doctor.services.thermal_optimizer.ThermalOptimizer.quit_app_gracefully",
        return_value=True,
    ) as mock_quit:
        result = optimizer.quit_app_gracefully("Xcode")

    assert result is True
    mock_quit.assert_called_once_with("Xcode")
