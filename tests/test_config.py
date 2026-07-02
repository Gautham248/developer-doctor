from pathlib import Path

from doctor.config import DoctorConfig, find_config_file, load_config


def test_load_config_returns_defaults_when_no_file(tmp_path: Path):
    config = load_config(path=tmp_path / "nonexistent.toml")
    assert config == DoctorConfig()


def test_load_config_returns_defaults_on_malformed_toml(tmp_path: Path):
    bad_file = tmp_path / "doctor.toml"
    bad_file.write_text("this is not [valid toml")
    config = load_config(path=bad_file)
    assert config == DoctorConfig()


def test_load_config_parses_plugin_disabled_list(tmp_path: Path):
    config_file = tmp_path / "doctor.toml"
    config_file.write_text('[plugins]\ndisabled = ["docker", "battery"]\n')
    config = load_config(path=config_file)
    assert config.plugins.disabled == ["docker", "battery"]


def test_load_config_parses_thresholds(tmp_path: Path):
    config_file = tmp_path / "doctor.toml"
    config_file.write_text(
        "[thresholds.cpu]\nwarn_percent = 60\nfail_percent = 85\n"
    )
    config = load_config(path=config_file)
    assert config.thresholds["cpu"]["warn_percent"] == 60
    assert config.thresholds["cpu"]["fail_percent"] == 85


def test_find_config_file_searches_parent_directories(tmp_path: Path):
    (tmp_path / "doctor.toml").write_text("")
    nested = tmp_path / "sub" / "deeper"
    nested.mkdir(parents=True)
    found = find_config_file(start=nested)
    assert found == tmp_path / "doctor.toml"


def test_find_config_file_returns_none_when_absent(tmp_path: Path):
    nested = tmp_path / "sub"
    nested.mkdir()
    found = find_config_file(start=nested)
    assert found is None