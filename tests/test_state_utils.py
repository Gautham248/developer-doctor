from pathlib import Path
from unittest.mock import patch

from doctor.utils.state import load_state, save_state
from doctor.utils.state import load_json, save_json


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

def test_json_roundtrip_with_arbitrary_structure(tmp_path: Path):
    with patch("doctor.utils.state._state_dir", return_value=tmp_path):
        save_json("test_key", {"nested": {"a": 1, "b": [1, 2, 3]}})
        result = load_json("test_key")

    assert result == {"nested": {"a": 1, "b": [1, 2, 3]}}


def test_load_json_returns_none_when_missing(tmp_path: Path):
    with patch("doctor.utils.state._state_dir", return_value=tmp_path):
        assert load_json("nonexistent") is None