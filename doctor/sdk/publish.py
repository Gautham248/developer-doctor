import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

PUBLISH_TIMEOUT_SECONDS = 120


@dataclass
class PublishResult:
    success: bool
    output: str
    dry_run: bool


def check_package(project_dir: Path) -> PublishResult:
    """Validate built distribution artifacts via `twine check`, without
    uploading anything — always the first step of `doctor plugin
    publish`, entirely local, no network access."""
    dist_dir = project_dir / "dist"
    artifacts = sorted(dist_dir.glob("*")) if dist_dir.is_dir() else []
    if not artifacts:
        return PublishResult(
            success=False,
            output=f"No built artifacts found in '{dist_dir}'. Run `doctor plugin package` first.",
            dry_run=True,
        )

    if shutil.which("twine") is None:
        return PublishResult(
            success=False,
            output="twine is not installed. Install it with `uv tool install twine` to publish.",
            dry_run=True,
        )

    try:
        result = subprocess.run(
            ["twine", "check", *[str(a) for a in artifacts]],
            capture_output=True,
            text=True,
            timeout=PUBLISH_TIMEOUT_SECONDS,
        )
        output = (result.stdout + result.stderr).strip()
        return PublishResult(success=result.returncode == 0, output=output, dry_run=True)
    except (subprocess.SubprocessError, OSError) as e:
        return PublishResult(success=False, output=f"Failed to run twine check: {e}", dry_run=True)


def upload_package(project_dir: Path, repository: str) -> PublishResult:
    """Actually upload built artifacts via `twine upload`. This is a
    real, irreversible action against an external package index and
    must never be invoked without explicit, out-of-band user
    confirmation — enforced at the CLI layer, not here."""
    dist_dir = project_dir / "dist"
    artifacts = sorted(dist_dir.glob("*")) if dist_dir.is_dir() else []
    if not artifacts:
        return PublishResult(
            success=False,
            output=f"No built artifacts found in '{dist_dir}'. Run `doctor plugin package` first.",
            dry_run=False,
        )

    if shutil.which("twine") is None:
        return PublishResult(
            success=False,
            output="twine is not installed. Install it with `uv tool install twine` to publish.",
            dry_run=False,
        )

    try:
        result = subprocess.run(
            ["twine", "upload", "--repository", repository, *[str(a) for a in artifacts]],
            capture_output=True,
            text=True,
            timeout=PUBLISH_TIMEOUT_SECONDS,
        )
        output = (result.stdout + result.stderr).strip()
        return PublishResult(success=result.returncode == 0, output=output, dry_run=False)
    except (subprocess.SubprocessError, OSError) as e:
        return PublishResult(success=False, output=f"Failed to run twine upload: {e}", dry_run=False)