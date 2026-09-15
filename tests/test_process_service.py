from unittest.mock import MagicMock, patch

from doctor.services.process_service import ProcessService
from doctor.services.thermal_service import KillSafety


def _mock_process(name: str, cpu: float, rss_bytes: float = 0.0) -> MagicMock:
    proc = MagicMock()
    proc.info = {"name": name}
    proc.name.return_value = name
    proc.cpu_percent.return_value = cpu
    proc.memory_info.return_value = MagicMock(rss=rss_bytes)
    return proc


def _mock_memory_proc(
    name: str, pid: int, rss_gb: float, username: str = "gautham", ppid: int = 1
) -> MagicMock:
    proc = MagicMock()
    proc.as_dict.return_value = {"pid": pid, "name": name, "username": username, "ppid": ppid}
    proc.memory_info.return_value = MagicMock(rss=rss_gb * (1024**3))
    return proc


def test_sample_system_and_processes_returns_sorted_top_processes():
    procs = [_mock_process("a", 5.0), _mock_process("b", 50.0), _mock_process("c", 20.0)]
    with (
        patch("psutil.process_iter", return_value=procs),
        patch("psutil.cpu_percent", return_value=42.0),
        patch("psutil.getloadavg", return_value=(1.0, 1.0, 1.0)),
        patch("time.sleep"),
    ):
        service = ProcessService()
        top, cpu_percent, load_avg = service.sample_system_and_processes(limit=2)

    assert cpu_percent == 42.0
    assert load_avg == (1.0, 1.0, 1.0)
    assert top == [("b", 50.0), ("c", 20.0)]


def test_sample_grouped_aggregates_by_classifier():
    procs = [
        _mock_process("Cursor Helper", 10.0, rss_bytes=1024**3),
        _mock_process("Cursor Helper 2", 5.0, rss_bytes=1024**3),
        _mock_process("Finder", 1.0),
    ]

    def classify(name: str) -> str | None:
        return "Cursor" if "cursor" in name.lower() else None

    with (
        patch("psutil.process_iter", return_value=procs),
        patch("time.sleep"),
    ):
        service = ProcessService()
        groups = service.sample_grouped(classify)

    assert "Cursor" in groups
    assert groups["Cursor"]["process_count"] == 2
    assert groups["Cursor"]["cpu_percent"] == 15.0


def test_sample_grouped_returns_empty_dict_when_nothing_matches():
    procs = [_mock_process("Finder", 1.0)]
    with patch("psutil.process_iter", return_value=procs):
        service = ProcessService()
        groups = service.sample_grouped(lambda name: None)

    assert groups == {}


def test_sample_memory_processes_returns_sorted_top_consumers():
    procs = [
        _mock_memory_proc("node", pid=61234, rss_gb=3.2),
        _mock_memory_proc("Brave Browser Helper", pid=61890, rss_gb=1.1),
        _mock_memory_proc("Finder", pid=100, rss_gb=0.2),
    ]
    with (
        patch("psutil.process_iter", return_value=procs),
        patch(
            "doctor.services.process_service.ThermalService._current_username",
            return_value="gautham",
        ),
        patch(
            "doctor.services.process_service.ThermalService._classify_kill_safety",
            return_value=(KillSafety.SAFE, "user-owned process"),
        ),
    ):
        service = ProcessService()
        top = service.sample_memory_processes(limit=2)

    assert [p.name for p in top] == ["node", "Brave Browser Helper"]
    assert top[0].rss_gb == 3.2
    assert top[0].pid == 61234
    assert top[0].kill_safety == KillSafety.SAFE


def test_sample_memory_processes_filters_below_min_rss():
    procs = [
        _mock_memory_proc("node", pid=61234, rss_gb=3.2),
        _mock_memory_proc("tiny_helper", pid=1, rss_gb=0.01),
    ]
    with (
        patch("psutil.process_iter", return_value=procs),
        patch(
            "doctor.services.process_service.ThermalService._current_username",
            return_value="gautham",
        ),
        patch(
            "doctor.services.process_service.ThermalService._classify_kill_safety",
            return_value=(KillSafety.SAFE, "user-owned process"),
        ),
    ):
        service = ProcessService()
        top = service.sample_memory_processes(min_rss_gb=0.1)

    assert [p.name for p in top] == ["node"]


def test_sample_memory_processes_skips_processes_that_vanish():
    import psutil as _psutil

    vanished = MagicMock()
    vanished.memory_info.side_effect = _psutil.NoSuchProcess(pid=999)
    alive = _mock_memory_proc("node", pid=61234, rss_gb=3.2)

    with (
        patch("psutil.process_iter", return_value=[vanished, alive]),
        patch(
            "doctor.services.process_service.ThermalService._current_username",
            return_value="gautham",
        ),
        patch(
            "doctor.services.process_service.ThermalService._classify_kill_safety",
            return_value=(KillSafety.SAFE, "user-owned process"),
        ),
    ):
        service = ProcessService()
        top = service.sample_memory_processes()

    assert [p.name for p in top] == ["node"]