from unittest.mock import MagicMock, patch

from doctor.models import Status
from doctor.plugins.memory import MemoryPlugin
from doctor.services.process_service import MemoryProcess
from doctor.services.thermal_service import KillSafety

PROCESS_PATCH_TARGET = "doctor.services.process_service.ProcessService.sample_memory_processes"


def _mock_vm(percent: float, used_gb: float, total_gb: float) -> MagicMock:
    vm = MagicMock()
    vm.percent = percent
    vm.used = used_gb * (1024**3)
    vm.total = total_gb * (1024**3)
    return vm


def _mock_swap(used_gb: float) -> MagicMock:
    swap = MagicMock()
    swap.used = used_gb * (1024**3)
    return swap


def _mock_memory_process(
    name: str,
    rss_gb: float,
    pid: int = 111,
    kill_safety: KillSafety = KillSafety.SAFE,
    kill_reason: str = "user-owned process",
) -> MemoryProcess:
    return MemoryProcess(
        pid=pid,
        name=name,
        rss_gb=rss_gb,
        username="gautham",
        ppid=1,
        kill_safety=kill_safety,
        kill_reason=kill_reason,
    )


def test_memory_plugin_passes_under_normal_usage():
    plugin = MemoryPlugin()
    with (
        patch("psutil.virtual_memory", return_value=_mock_vm(50.0, 8.0, 16.0)),
        patch("psutil.swap_memory", return_value=_mock_swap(0.0)),
        patch(PROCESS_PATCH_TARGET) as mock_sample,
    ):
        result = plugin.run()

    assert result.status == Status.PASS
    assert result.score_delta == 0
    # PASS never needs a process breakdown — keeps the common path fast.
    mock_sample.assert_not_called()


def test_memory_plugin_warns_on_high_ram():
    plugin = MemoryPlugin()
    with (
        patch("psutil.virtual_memory", return_value=_mock_vm(85.0, 13.6, 16.0)),
        patch("psutil.swap_memory", return_value=_mock_swap(0.0)),
        patch(PROCESS_PATCH_TARGET, return_value=[]),
    ):
        result = plugin.run()

    assert result.status == Status.WARN
    assert result.score_delta == 5


def test_memory_plugin_fails_on_critical_ram():
    plugin = MemoryPlugin()
    with (
        patch("psutil.virtual_memory", return_value=_mock_vm(97.0, 15.5, 16.0)),
        patch("psutil.swap_memory", return_value=_mock_swap(0.0)),
        patch(PROCESS_PATCH_TARGET, return_value=[]),
    ):
        result = plugin.run()

    assert result.status == Status.FAIL
    assert result.score_delta == 15


def test_memory_plugin_fails_on_heavy_swap():
    plugin = MemoryPlugin()
    with (
        patch("psutil.virtual_memory", return_value=_mock_vm(60.0, 9.6, 16.0)),
        patch("psutil.swap_memory", return_value=_mock_swap(9.0)),
        patch(PROCESS_PATCH_TARGET, return_value=[]),
    ):
        result = plugin.run()

    assert result.status == Status.FAIL
    assert result.score_delta == 15
    assert any("swap" in rec.lower() for rec in result.recommendations)


def test_memory_plugin_never_raises_on_psutil_failure():
    plugin = MemoryPlugin()
    with patch("psutil.virtual_memory", side_effect=RuntimeError("boom")):
        result = plugin.run()

    assert result.status == Status.FAIL
    assert "Could not read memory information" in result.findings[0].summary


def test_memory_plugin_names_top_process_when_fail():
    """This is the case from the reported bug: a generic 'restart memory-heavy
    applications' message with no indication of which application."""
    plugin = MemoryPlugin()
    top = [
        _mock_memory_process("node", 3.2, pid=61234),
        _mock_memory_process("Brave Browser Helper", 1.1, pid=61890),
    ]
    with (
        patch("psutil.virtual_memory", return_value=_mock_vm(79.0, 8.8, 24.0)),
        patch("psutil.swap_memory", return_value=_mock_swap(10.6)),
        patch(PROCESS_PATCH_TARGET, return_value=top),
    ):
        result = plugin.run()

    assert result.status == Status.FAIL
    summaries = [f.summary for f in result.findings]
    assert "node: 3.2 GB RSS" in summaries
    assert "Brave Browser Helper: 1.1 GB RSS" in summaries
    assert any(
        "node" in rec and "61234" in rec and "3.2 GB" in rec
        for rec in result.recommendations
    )


def test_memory_plugin_advises_caution_for_unsafe_top_process():
    plugin = MemoryPlugin()
    top = [
        _mock_memory_process(
            "mds_stores",
            2.0,
            pid=42,
            kill_safety=KillSafety.CAUTION,
            kill_reason="system daemon — killing may affect stability",
        )
    ]
    with (
        patch("psutil.virtual_memory", return_value=_mock_vm(85.0, 13.6, 16.0)),
        patch("psutil.swap_memory", return_value=_mock_swap(0.0)),
        patch(PROCESS_PATCH_TARGET, return_value=top),
    ):
        result = plugin.run()

    assert result.status == Status.WARN
    assert any(
        "caution" in rec.lower() and "mds_stores" in rec for rec in result.recommendations
    )


def test_memory_plugin_process_sampling_failure_does_not_fail_the_check():
    """A sampling error is enrichment failing, not the RAM/swap reading itself —
    the plugin must still report the real status."""
    plugin = MemoryPlugin()
    with (
        patch("psutil.virtual_memory", return_value=_mock_vm(97.0, 15.5, 16.0)),
        patch("psutil.swap_memory", return_value=_mock_swap(0.0)),
        patch(PROCESS_PATCH_TARGET, side_effect=RuntimeError("boom")),
    ):
        result = plugin.run()

    assert result.status == Status.FAIL
    assert result.score_delta == 15