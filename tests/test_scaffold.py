from pathlib import Path

import pytest

from doctor.sdk.scaffold import scaffold_plugin


def test_scaffold_plugin_creates_expected_structure(tmp_path: Path):
    target = scaffold_plugin("postgres", target_dir=tmp_path)

    assert target == tmp_path / "doctor-plugin-postgres"
    assert (target / "pyproject.toml").exists()
    assert (target / "README.md").exists()
    assert (target / "LICENSE").exists()
    assert (target / "doctor_plugin_postgres" / "__init__.py").exists()
    assert (target / "doctor_plugin_postgres" / "plugin.py").exists()
    assert (target / "tests" / "test_plugin.py").exists()
    assert (target / ".github" / "workflows" / "ci.yml").exists()


def test_scaffold_plugin_generates_valid_python(tmp_path: Path):
    target = scaffold_plugin("my-cool-thing", target_dir=tmp_path)
    plugin_source = (target / "doctor_plugin_my_cool_thing" / "plugin.py").read_text()

    assert "class MyCoolThingPlugin(DoctorPlugin):" in plugin_source
    assert 'name = "my-cool-thing"' in plugin_source


def test_scaffold_plugin_rejects_invalid_name(tmp_path: Path):
    with pytest.raises(ValueError):
        scaffold_plugin("Not Valid!", target_dir=tmp_path)


def test_scaffold_plugin_rejects_existing_directory(tmp_path: Path):
    scaffold_plugin("dupe", target_dir=tmp_path)
    with pytest.raises(ValueError):
        scaffold_plugin("dupe", target_dir=tmp_path)


def test_scaffold_plugin_entry_point_matches_class(tmp_path: Path):
    target = scaffold_plugin("postgres", target_dir=tmp_path)
    pyproject = (target / "pyproject.toml").read_text()

    assert 'postgres = "doctor_plugin_postgres.plugin:PostgresPlugin"' in pyproject