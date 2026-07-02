import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

BUILD_TIMEOUT_SECONDS = 120


@dataclass
class PackageResult:
    success: bool
    output: str
    artifacts: list[Path]


def package_plugin(project_dir: Path) -> PackageResult:
    """Build a plugin into a wheel + sdist via `uv build` (§22.5's
    `doctor plugin package`). Reuses uv rather than introducing a
    second build backend just for plugin authors, since this project
    already depends on uv for its own build."""
    pyproject = project_dir / "pyproject.toml"
    if not pyproject.is_file():
        return PackageResult(
            success=False,
            output=f"No pyproject.toml found in '{project_dir}'.",
            artifacts=[],
        )

    if shutil.which("uv") is None:
        return PackageResult(success=False, output="uv is not installed or not on PATH.", artifacts=[])

    try:
        result = subprocess.run(
            ["uv", "build"],
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=BUILD_TIMEOUT_SECONDS,
        )
        output = (result.stdout + result.stderr).strip()
        if result.returncode != 0:
            return PackageResult(success=False, output=output, artifacts=[])

        dist_dir = project_dir / "dist"
        artifacts = sorted(dist_dir.glob("*")) if dist_dir.is_dir() else []
        return PackageResult(success=True, output=output, artifacts=artifacts)
    except (subprocess.SubprocessError, OSError) as e:
        return PackageResult(success=False, output=f"Failed to run uv build: {e}", artifacts=[])