from pathlib import Path
from unittest.mock import patch

from doctor.utils.state import load_state, save_state


def test_state_roundtrip(tmp_path: Path):
    with patch("doctor.utils.state._state_dir", return_value=tmp_path):
        save_state("test_key", {"foo": "bar"})
        result = load_state("test_key")

    assert result == {"foo": "bar"}


def test_load_state_returns_empty_dict_when_missing(tmp_path: Path):
    with patch("doctor.utils.state._state_dir", return_value=tmp_path):
        result = load_state("nonexistent_key")

    assert result == {}


def test_load_state_returns_empty_dict_on_corrupted_file(tmp_path: Path):
    (tmp_path / "bad_key.json").write_text("{not valid json")
    with patch("doctor.utils.state._state_dir", return_value=tmp_path):
        result = load_state("bad_key")

    assert result == {}