from unittest.mock import MagicMock, patch

from doctor.services.process_service import ProcessService


def _mock_process(name: str, cpu: float, rss_bytes: float = 0.0) -> MagicMock:
    proc = MagicMock()
    proc.info = {"name": name}
    proc.name.return_value = name
    proc.cpu_percent.return_value = cpu
    proc.memory_info.return_value = MagicMock(rss=rss_bytes)
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