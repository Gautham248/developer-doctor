from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from doctor.cli import app
from doctor.services.process_service import MemoryProcess
from doctor.services.thermal_service import KillSafety

runner = CliRunner()

VM_PATCH = "psutil.virtual_memory"
SWAP_PATCH = "psutil.swap_memory"
SAMPLE_PATCH = "doctor.services.process_service.ProcessService.sample_memory_processes"


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


def _proc(name: str, pid: int, rss_gb: float, kill_safety=KillSafety.SAFE) -> MemoryProcess:
    return MemoryProcess(
        pid=pid,
        name=name,
        rss_gb=rss_gb,
        username="gautham",
        ppid=1,
        kill_safety=kill_safety,
        kill_reason="user-owned process",
    )


def test_memory_cmd_renders_header_and_process_table():
    with (
        patch(VM_PATCH, return_value=_mock_vm(60.0, 12.1, 24.0)),
        patch(SWAP_PATCH, return_value=_mock_swap(8.3)),
        patch(SAMPLE_PATCH, return_value=[_proc("Electron", 1331, 2.1)]),
    ):
        result = runner.invoke(app, ["memory"])

    assert result.exit_code == 0
    assert "12.1 GB" in result.stdout
    assert "8.3 GB" in result.stdout
    assert "Electron" in result.stdout
    assert "1331" in result.stdout


def test_memory_cmd_optimize_shows_plan_and_declines_by_default():
    with (
        patch(VM_PATCH, return_value=_mock_vm(60.0, 12.1, 24.0)),
        patch(SWAP_PATCH, return_value=_mock_swap(8.3)),
        patch(SAMPLE_PATCH, return_value=[_proc("Electron", 1331, 2.1)]),
    ):
        # CliRunner feeds 'none' to the "Apply actions?" prompt via input.
        result = runner.invoke(app, ["memory", "--optimize"], input="none\n")

    assert result.exit_code == 0
    assert "Optimization Plan" in result.stdout
    assert "Electron" in result.stdout
    assert "No actions applied." in result.stdout


def test_memory_cmd_optimize_applies_selected_action():
    with (
        patch(VM_PATCH, return_value=_mock_vm(60.0, 12.1, 24.0)),
        patch(SWAP_PATCH, return_value=_mock_swap(8.3)),
        patch(SAMPLE_PATCH, return_value=[_proc("my_custom_script", 1331, 2.1)]),
        patch(
            "doctor.services.thermal_optimizer.ThermalOptimizer.terminate_process",
            return_value=True,
        ) as mock_terminate,
    ):
        result = runner.invoke(app, ["memory", "--optimize"], input="1\n")

    assert result.exit_code == 0
    assert "Optimization complete." in result.stdout
    mock_terminate.assert_called_once_with(1331, force=True)


def test_memory_cmd_auto_optimize_applies_without_prompting():
    with (
        patch(VM_PATCH, return_value=_mock_vm(60.0, 12.1, 24.0)),
        patch(SWAP_PATCH, return_value=_mock_swap(8.3)),
        patch(SAMPLE_PATCH, return_value=[_proc("my_custom_script", 1331, 2.1)]),
        patch(
            "doctor.services.thermal_optimizer.ThermalOptimizer.terminate_process",
            return_value=True,
        ) as mock_terminate,
    ):
        result = runner.invoke(app, ["memory", "--auto-optimize"])

    assert result.exit_code == 0
    mock_terminate.assert_called_once_with(1331, force=True)


def test_memory_cmd_kill_terminates_selected_pid():
    with (
        patch(VM_PATCH, return_value=_mock_vm(60.0, 12.1, 24.0)),
        patch(SWAP_PATCH, return_value=_mock_swap(8.3)),
        patch(SAMPLE_PATCH, return_value=[_proc("Electron", 1331, 2.1)]),
        patch(
            "doctor.services.thermal_optimizer.ThermalOptimizer.terminate_process",
            return_value=True,
        ) as mock_terminate,
    ):
        result = runner.invoke(app, ["memory", "--kill"], input="1331\ny\nq\n")

    assert result.exit_code == 0
    mock_terminate.assert_called_once_with(1331, force=True)


def test_memory_cmd_optimize_with_no_processes():
    with (
        patch(VM_PATCH, return_value=_mock_vm(30.0, 6.0, 24.0)),
        patch(SWAP_PATCH, return_value=_mock_swap(0.0)),
        patch(SAMPLE_PATCH, return_value=[]),
    ):
        result = runner.invoke(app, ["memory", "--optimize"])

    assert result.exit_code == 0
    assert "No optimization opportunities found." in result.stdout
