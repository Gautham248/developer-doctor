"""Tests for ThermalService — mocking subprocess calls and sysfs reads."""

from __future__ import annotations

import platform
from unittest.mock import MagicMock, patch

import pytest

from doctor.services.thermal_service import (
    KillSafety,
    ThermalService,
    SOURCE_MACOS_POWERMETRICS,
    SOURCE_MACOS_SWIFT,
    SOURCE_UNAVAILABLE,
    LEVEL_NOMINAL,
    LEVEL_FAIR,
    LEVEL_SERIOUS,
    LEVEL_CRITICAL,
    LEVEL_UNKNOWN,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

MOCK_POWERMETRICS_OUTPUT = """
Machine model: MacBook Air (Apple M5)
EFI version: 18000.120.36

**** Thermal Info ****
Thermal pressure: Nominal

**** CPU Power Info ****
CPU Power: 3241 mW

**** GPU Power Info ****
GPU Power: 512 mW

**** ANE Power Info ****
ANE Power: 0 mW
"""

MOCK_POWERMETRICS_SERIOUS = """
**** Thermal Info ****
Thermal pressure: Serious
CPU Power: 8200 mW
GPU Power: 1500 mW
ANE Power: 400 mW
"""


def _make_proc(pid, name, username, ppid, cpu=5.0):
    """Build a minimal psutil.Process-like mock."""
    p = MagicMock()
    p.pid = pid
    p.info = {"pid": pid, "name": name, "username": username, "ppid": ppid}
    p.cpu_percent.return_value = cpu
    p.as_dict.return_value = {"pid": pid, "name": name, "username": username, "ppid": ppid}
    return p


# ---------------------------------------------------------------------------
# macOS powermetrics path
# ---------------------------------------------------------------------------

@patch("platform.system", return_value="Darwin")
@patch("doctor.services.thermal_service.ThermalService._check_pmset_warnings", return_value=False)
@patch("subprocess.run")
def test_macos_powermetrics_nominal(mock_run, _pmset, _platform):
    result = MagicMock()
    result.returncode = 0
    result.stdout = MOCK_POWERMETRICS_OUTPUT
    mock_run.return_value = result

    state = ThermalService().get_thermal_state()

    assert state.level == LEVEL_NOMINAL
    assert state.cpu_power_mw == 3241.0
    assert state.gpu_power_mw == 512.0
    assert state.ane_power_mw == 0.0
    assert state.source == SOURCE_MACOS_POWERMETRICS
    assert state.temperature_c is None


@patch("platform.system", return_value="Darwin")
@patch("doctor.services.thermal_service.ThermalService._check_pmset_warnings", return_value=False)
@patch("subprocess.run")
def test_macos_powermetrics_serious(mock_run, _pmset, _platform):
    result = MagicMock()
    result.returncode = 0
    result.stdout = MOCK_POWERMETRICS_SERIOUS
    mock_run.return_value = result

    state = ThermalService().get_thermal_state()

    assert state.level == LEVEL_SERIOUS
    assert state.cpu_power_mw == 8200.0
    assert state.source == SOURCE_MACOS_POWERMETRICS


# ---------------------------------------------------------------------------
# macOS Swift fallback
# ---------------------------------------------------------------------------

@patch("platform.system", return_value="Darwin")
@patch("doctor.services.thermal_service.ThermalService._check_pmset_warnings", return_value=False)
@patch("subprocess.run")
def test_macos_falls_back_to_swift_when_powermetrics_fails(mock_run, _pmset, _platform):
    # First call (powermetrics) fails, second call (swift) succeeds
    pm_fail = MagicMock()
    pm_fail.returncode = 1
    pm_fail.stdout = ""

    swift_ok = MagicMock()
    swift_ok.returncode = 0
    swift_ok.stdout = "1\n"  # thermalState = fair

    mock_run.side_effect = [pm_fail, swift_ok]

    state = ThermalService().get_thermal_state()

    assert state.level == LEVEL_FAIR
    assert state.cpu_power_mw is None
    assert state.source == SOURCE_MACOS_SWIFT


@patch("platform.system", return_value="Darwin")
@patch("subprocess.run")
def test_macos_both_fail_returns_unknown(mock_run, _platform):
    fail = MagicMock()
    fail.returncode = 1
    fail.stdout = ""
    mock_run.return_value = fail

    state = ThermalService().get_thermal_state()

    assert state.level == LEVEL_UNKNOWN
    assert state.source in (SOURCE_MACOS_SWIFT, SOURCE_UNAVAILABLE)


@patch("platform.system", return_value="Darwin")
@patch("doctor.services.thermal_service.ThermalService._check_pmset_warnings", return_value=False)
@patch("subprocess.run")
def test_swift_thermal_states_map_correctly(mock_run, _pmset, _platform):
    pm_fail = MagicMock()
    pm_fail.returncode = 1
    pm_fail.stdout = ""

    for raw_value, expected_level in [("0", LEVEL_NOMINAL), ("1", LEVEL_FAIR), ("2", LEVEL_SERIOUS), ("3", LEVEL_CRITICAL)]:
        swift_ok = MagicMock()
        swift_ok.returncode = 0
        swift_ok.stdout = f"{raw_value}\n"
        mock_run.side_effect = [pm_fail, swift_ok]
        state = ThermalService().get_thermal_state()
        assert state.level == expected_level, f"rawValue={raw_value}"


# ---------------------------------------------------------------------------
# Linux sysfs path
# ---------------------------------------------------------------------------

@patch("platform.system", return_value="Linux")
@patch("os.path.isdir", return_value=True)
@patch("os.listdir", return_value=["thermal_zone0", "thermal_zone1"])
def test_linux_sysfs_serious(_platform, _isdir, _listdir):
    # Patch open to return 82000 (82.0°C) for all zone temp files
    mock_open = MagicMock()
    mock_open.return_value.__enter__ = lambda s: s
    mock_open.return_value.__exit__ = MagicMock(return_value=False)
    mock_open.return_value.read.return_value = "82000"

    with patch("builtins.open", mock_open):
        state = ThermalService().get_thermal_state()

    assert state.temperature_c == 82.0
    assert state.level == LEVEL_SERIOUS


@patch("platform.system", return_value="Linux")
@patch("os.path.isdir", return_value=True)
@patch("os.listdir", return_value=["thermal_zone0"])
def test_linux_sysfs_nominal(_platform, _isdir, _listdir):
    mock_open = MagicMock()
    mock_open.return_value.__enter__ = lambda s: s
    mock_open.return_value.__exit__ = MagicMock(return_value=False)
    mock_open.return_value.read.return_value = "45000"  # 45°C

    with patch("builtins.open", mock_open):
        state = ThermalService().get_thermal_state()

    assert state.temperature_c == 45.0
    assert state.level == LEVEL_NOMINAL


# ---------------------------------------------------------------------------
# Kill safety classification
# ---------------------------------------------------------------------------

def test_kernel_task_is_unsafe():
    safety, _ = ThermalService._classify_kill_safety(0, "kernel_task", "root", "user")
    assert safety == KillSafety.UNSAFE


def test_launchd_is_unsafe():
    safety, _ = ThermalService._classify_kill_safety(1, "launchd", "root", "user")
    assert safety == KillSafety.UNSAFE


def test_window_server_is_unsafe():
    safety, _ = ThermalService._classify_kill_safety(500, "WindowServer", "root", "user")
    assert safety == KillSafety.UNSAFE


def test_root_logd_is_caution():
    safety, _ = ThermalService._classify_kill_safety(200, "logd", "root", "user")
    assert safety == KillSafety.CAUTION


def test_unknown_root_process_is_caution():
    safety, _ = ThermalService._classify_kill_safety(999, "some_daemon", "root", "user")
    assert safety == KillSafety.CAUTION


def test_user_process_is_safe():
    safety, _ = ThermalService._classify_kill_safety(1234, "Xcode", "gautham", "gautham")
    assert safety == KillSafety.SAFE


def test_renderer_process_safe_when_user_owned():
    safety, _ = ThermalService._classify_kill_safety(
        5678, "Brave Browser Helper (Renderer)", "gautham", "gautham"
    )
    assert safety == KillSafety.SAFE
