import re
from datetime import date
from pathlib import Path

NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_-]*$")


def validate_plugin_name(name: str) -> None:
    if not NAME_PATTERN.match(name):
        raise ValueError(
            f"Invalid plugin name '{name}'. Must start with a lowercase letter "
            f"and contain only lowercase letters, digits, hyphens, or underscores."
        )


def _to_class_name(name: str) -> str:
    parts = re.split(r"[-_]", name)
    return "".join(p.capitalize() for p in parts if p) + "Plugin"


def _to_package_name(name: str) -> str:
    return name.replace("-", "_")


def scaffold_plugin(name: str, target_dir: Path | None = None) -> Path:
    """Scaffold a new third-party plugin package (§22.5).

    Generates a standalone, pip-installable package with a working
    sample plugin, tests using PluginTestHarness, a GitHub Actions CI
    workflow, README, and LICENSE — registered via the same
    'doctor.plugins' entry point group discovery.py already reads.

    Raises ValueError on an invalid name or if the target directory
    already exists — never silently overwrites.
    """
    validate_plugin_name(name)

    base = target_dir or Path.cwd()
    project_dir = base / f"doctor-plugin-{name}"
    if project_dir.exists():
        raise ValueError(f"Directory '{project_dir}' already exists.")

    package_name = f"doctor_plugin_{_to_package_name(name)}"
    class_name = _to_class_name(name)
    year = date.today().year

    package_dir = project_dir / package_name
    tests_dir = project_dir / "tests"
    workflow_dir = project_dir / ".github" / "workflows"
    for d in (package_dir, tests_dir, workflow_dir):
        d.mkdir(parents=True)

    (package_dir / "__init__.py").write_text("")

    (package_dir / "plugin.py").write_text(
        f'''from doctor.capabilities import Capability
from doctor.models import Finding, PluginResult, Status
from doctor.plugins.base import DoctorPlugin


class {class_name}(DoctorPlugin):
    name = "{name}"
    description = "TODO: describe what this plugin checks."
    # Declare capabilities from doctor.capabilities.Capability as needed,
    # e.g. capabilities: list[Capability] = [Capability.SHELL_COMMANDS]
    capabilities: list[Capability] = []

    def is_supported(self) -> bool:
        # TODO: return False here if this plugin shouldn't run on this
        # platform or when a required tool isn't installed.
        return True

    def run(self) -> PluginResult:
        try:
            # TODO: implement your diagnostic here.
            return PluginResult(
                plugin_name=self.name,
                status=Status.INFO,
                findings=[
                    Finding(summary="Hello from the {name} plugin! Replace this with a real check.")
                ],
            )
        except Exception as e:
            return PluginResult(
                plugin_name=self.name,
                status=Status.FAIL,
                findings=[Finding(summary="Could not run {name} diagnostics", detail=str(e))],
            )
'''
    )

    (tests_dir / "test_plugin.py").write_text(
        f'''from doctor.models import Status
from doctor.sdk.testing import PluginTestHarness

from {package_name}.plugin import {class_name}


def test_plugin_runs_without_raising():
    harness = PluginTestHarness()
    result = harness.run({class_name}())
    assert result.status in (Status.PASS, Status.WARN, Status.FAIL, Status.INFO)


def test_plugin_has_required_metadata():
    plugin = {class_name}()
    assert plugin.name == "{name}"
    assert plugin.description
'''
    )

    (project_dir / "pyproject.toml").write_text(
        f'''[project]
name = "doctor-plugin-{name}"
version = "0.1.0"
description = "A Developer Doctor plugin: {name}"
requires-python = ">=3.11"
dependencies = [
    "developer-doctor",
]

[project.entry-points."doctor.plugins"]
{name} = "{package_name}.plugin:{class_name}"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["{package_name}"]

[dependency-groups]
dev = ["pytest"]
'''
    )

    (project_dir / "README.md").write_text(
        f'''# doctor-plugin-{name}

A [Developer Doctor](https://github.com/) plugin.

## Status

⚠️ `developer-doctor` is not yet published to PyPI. Until it is, install
both packages in the same environment from local checkouts, e.g.:

```bash
uv pip install -e /path/to/dev-doctor
uv pip install -e .
```

Once both are installed in the same environment, running `doctor` will
automatically discover this plugin via its `doctor.plugins` entry point
— no further registration needed.

## Development

```bash
pytest
```

## Structure

- `{package_name}/plugin.py` — the plugin implementation
- `tests/test_plugin.py` — tests using `PluginTestHarness`
'''
    )

    (project_dir / "LICENSE").write_text(
        f'''MIT License

Copyright (c) {year} [Your Name]

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to
deal in the Software without restriction, including without limitation the
rights to use, copy, modify, merge, publish, distribute, sublicense, and/or
sell copies of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND.
'''
    )

    (workflow_dir / "ci.yml").write_text(
        '''name: CI
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
      - run: uv pip install --system -e .
      - run: uv pip install --system pytest
      - run: pytest
'''
    )

    return project_dir