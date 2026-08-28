"""Tests for ThermalPlugin — status/score mapping and resilience."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from doctor.models import Status
from doctor.plugins.thermal import ThermalPlugin
from doctor.services.thermal_service import (
    LEVEL_NOMINAL,
    LEVEL_FAIR,
    LEVEL_SERIOUS,
    LEVEL_CRITICAL,
    ThermalState,
    SOURCE_MACOS_SWIFT,
)

PATCH_STATE = "doctor.services.thermal_service.ThermalService.get_thermal_state"
PATCH_PROCS = "doctor.services.thermal_service.ThermalService.get_thermal_processes"


def _state(level: str, **kwargs) -> ThermalState:
    return ThermalState(level=level, source=SOURCE_MACOS_SWIFT, **kwargs)


# ---------------------------------------------------------------------------
# Status and score mapping
# ---------------------------------------------------------------------------

def test_nominal_is_pass():
    plugin = ThermalPlugin()
    with patch(PATCH_STATE, return_value=_state(LEVEL_NOMINAL)), \
         patch(PATCH_PROCS, return_value=[]):
        result = plugin.run()
    assert result.status == Status.PASS
    assert result.score_delta == 0


def test_fair_is_warn():
    plugin = ThermalPlugin()
    with patch(PATCH_STATE, return_value=_state(LEVEL_FAIR)), \
         patch(PATCH_PROCS, return_value=[]):
        result = plugin.run()
    assert result.status == Status.WARN
    assert result.score_delta == 5


def test_serious_is_fail_with_delta_15():
    plugin = ThermalPlugin()
    with patch(PATCH_STATE, return_value=_state(LEVEL_SERIOUS)), \
         patch(PATCH_PROCS, return_value=[]):
        result = plugin.run()
    assert result.status == Status.FAIL
    assert result.score_delta == 15


def test_critical_is_fail_with_delta_20():
    plugin = ThermalPlugin()
    with patch(PATCH_STATE, return_value=_state(LEVEL_CRITICAL)), \
         patch(PATCH_PROCS, return_value=[]):
        result = plugin.run()
    assert result.status == Status.FAIL
    assert result.score_delta == 20


# ---------------------------------------------------------------------------
# Recommendations
# ---------------------------------------------------------------------------

def test_serious_recommendation_mentions_optimize():
    from doctor.services.thermal_service import ThermalProcess, KillSafety
    hot_proc = ThermalProcess(
        pid=1234, name="Xcode", cpu_percent=120.0,
        username="gautham", ppid=1,
        kill_safety=KillSafety.SAFE, kill_reason="user-owned"
    )
    plugin = ThermalPlugin()
    with patch(PATCH_STATE, return_value=_state(LEVEL_SERIOUS)), \
         patch(PATCH_PROCS, return_value=[hot_proc]):
        result = plugin.run()
    assert any("--optimize" in r for r in result.recommendations)
    assert any("Xcode" in r for r in result.recommendations)


def test_nominal_has_no_recommendations():
    plugin = ThermalPlugin()
    with patch(PATCH_STATE, return_value=_state(LEVEL_NOMINAL)), \
         patch(PATCH_PROCS, return_value=[]):
        result = plugin.run()
    assert result.recommendations == []


# ---------------------------------------------------------------------------
# Linux temperature threshold override
# ---------------------------------------------------------------------------

def test_linux_high_temp_triggers_fail():
    plugin = ThermalPlugin()
    linux_state = ThermalState(
        level=LEVEL_NOMINAL,  # pressure says nominal...
        temperature_c=85.0,   # ...but sysfs says 85°C
        source="linux_sysfs",
    )
    with patch(PATCH_STATE, return_value=linux_state), \
         patch(PATCH_PROCS, return_value=[]):
        result = plugin.run()
    # Temperature threshold should override the nominal level
    assert result.status == Status.FAIL


def test_linux_moderate_temp_triggers_warn():
    plugin = ThermalPlugin()
    linux_state = ThermalState(
        level=LEVEL_NOMINAL,
        temperature_c=65.0,
        source="linux_sysfs",
    )
    with patch(PATCH_STATE, return_value=linux_state), \
         patch(PATCH_PROCS, return_value=[]):
        result = plugin.run()
    assert result.status == Status.WARN


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------

def test_metadata_contains_thermal_fields():
    plugin = ThermalPlugin()
    state = ThermalState(
        level=LEVEL_NOMINAL,
        cpu_power_mw=3241.0,
        gpu_power_mw=512.0,
        ane_power_mw=0.0,
        source="macos_powermetrics",
    )
    with patch(PATCH_STATE, return_value=state), \
         patch(PATCH_PROCS, return_value=[]):
        result = plugin.run()

    assert result.metadata["thermal_level"] == LEVEL_NOMINAL
    assert result.metadata["cpu_power_mw"] == 3241.0
    assert result.metadata["gpu_power_mw"] == 512.0
    assert result.metadata["source"] == "macos_powermetrics"


# ---------------------------------------------------------------------------
# Resilience — plugin must never raise
# ---------------------------------------------------------------------------

def test_plugin_never_raises_on_failure():
    plugin = ThermalPlugin()
    with patch(PATCH_STATE, side_effect=RuntimeError("boom")):
        result = plugin.run()
    assert result.status == Status.FAIL
    assert "Could not read thermal information" in result.findings[0].summary
