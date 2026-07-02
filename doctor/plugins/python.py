import shutil
import sys
from pathlib import Path

from doctor.models import Finding, PluginResult, Status
from doctor.plugins.base import DoctorPlugin
from doctor.capabilities import Capability

class PythonPlugin(DoctorPlugin):
    name = "python"
    description = "Detects active Python version, virtualenv state, and version manager (mise/pyenv/system)."
    capabilities = [Capability.FILESYSTEM_READ]

    def is_supported(self) -> bool:
        return shutil.which("python3") is not None or shutil.which("python") is not None

    def run(self) -> PluginResult:
        try:
            version = self._python_version()
            in_venv = self._in_virtualenv()

            findings: list[Finding] = [Finding(summary=f"Python {version}")]
            recommendations: list[str] = []
            status = Status.PASS
            score_delta = 0

            # Base interpreter manager: always checked against sys.base_prefix
            # (the interpreter a venv was built from, or sys.prefix itself if
            # there's no venv), since sys.executable inside an active venv
            # only tells us who made the venv, not what's underneath it.
            base_manager = self._detect_version_manager(sys.base_prefix)

            if in_venv:
                venv_name = Path(sys.prefix).name
                venv_tool = self._detect_venv_tool()
                findings.append(
                    Finding(summary=f"Active virtualenv: {venv_name} (created by {venv_tool})")
                )
                findings.append(Finding(summary=f"Base interpreter managed by: {base_manager}"))
            else:
                findings.append(Finding(summary=f"Managed by: {base_manager}"))
                cwd_has_project = self._cwd_looks_like_python_project()
                findings.append(Finding(summary="No active virtualenv"))
                if cwd_has_project:
                    status = Status.WARN
                    score_delta = 5
                    recommendations.append(
                        "This directory looks like a Python project, but no virtualenv is "
                        "active. Installing packages globally can lead to version conflicts "
                        "across projects."
                    )

            conflicting_managers = self._detect_conflicting_managers()
            if len(conflicting_managers) > 1:
                status = Status.WARN
                score_delta = max(score_delta, 5)
                findings.append(
                    Finding(
                        summary=f"Multiple Python version managers detected: "
                        f"{', '.join(conflicting_managers)}"
                    )
                )
                recommendations.append(
                    f"Having multiple Python version managers installed "
                    f"({', '.join(conflicting_managers)}) can cause the wrong interpreter "
                    f"to be picked up depending on shell startup order. Consider "
                    f"standardizing on one."
                )

            return PluginResult(
                plugin_name=self.name,
                status=status,
                score_delta=score_delta,
                findings=findings,
                recommendations=recommendations,
                metadata={
                    "version": version,
                    "python_path": sys.executable,
                    "base_prefix": sys.base_prefix,
                    "base_manager": base_manager,
                    "in_venv": in_venv,
                    "venv_tool": self._detect_venv_tool() if in_venv else None,
                    "conflicting_managers": conflicting_managers,
                },
            )
        except Exception as e:
            return PluginResult(
                plugin_name=self.name,
                status=Status.FAIL,
                findings=[Finding(summary="Could not run Python diagnostics", detail=str(e))],
            )

    def _python_version(self) -> str:
        return f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"

    def _in_virtualenv(self) -> bool:
        """True if the currently running interpreter is inside a virtualenv.

        Note: this reflects the interpreter running `doctor` itself, not
        necessarily any other Python environment on the system. That's an
        inherent limitation of checking from within a running process.
        """
        return sys.prefix != sys.base_prefix

    def _detect_venv_tool(self) -> str:
        """Identify what created the active venv, via pyvenv.cfg markers.

        uv and stdlib venv/virtualenv all write a pyvenv.cfg into the venv
        root with distinguishing fields — this reads it rather than
        guessing from the path alone.
        """
        pyvenv_cfg = Path(sys.prefix) / "pyvenv.cfg"
        if not pyvenv_cfg.exists():
            return "unknown"
        try:
            content = pyvenv_cfg.read_text().lower()
        except OSError:
            return "unknown"

        if "uv" in content:
            return "uv"
        if "virtualenv" in content:
            return "virtualenv"
        return "venv"

    def _detect_version_manager(self, interpreter_path: str) -> str:
        """Infer which tool controls a given interpreter, from its resolved path."""
        if "/.local/share/mise/" in interpreter_path or "/mise/" in interpreter_path:
            return "mise"
        if "/.pyenv/" in interpreter_path:
            return "pyenv"
        if "/homebrew/" in interpreter_path or "/opt/homebrew/" in interpreter_path:
            return "homebrew"
        if interpreter_path in ("/usr/bin/python3", "/usr/local/bin/python3", "/usr/bin", "/usr"):
            return "system"
        return "system"

    def _cwd_looks_like_python_project(self) -> bool:
        cwd = Path.cwd()
        markers = ["pyproject.toml", "setup.py", "requirements.txt"]
        return any((cwd / marker).exists() for marker in markers)

    def _detect_conflicting_managers(self) -> list[str]:
        """Check for signs of multiple Python version managers installed at once."""
        found = []
        if (Path.home() / ".pyenv").exists():
            found.append("pyenv")
        if (Path.home() / ".local" / "share" / "mise").exists() or shutil.which("mise"):
            found.append("mise")
        return found