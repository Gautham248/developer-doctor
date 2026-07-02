import shutil
import subprocess
from pathlib import Path

from doctor.models import Finding, PluginResult, Status
from doctor.plugins.base import DoctorPlugin

NODE_TIMEOUT_SECONDS = 5


class NodePlugin(DoctorPlugin):
    name = "node"
    description = "Detects Node.js version, active package manager, and version manager (mise/nvm/system)."

    def is_supported(self) -> bool:
        return shutil.which("node") is not None

    def run(self) -> PluginResult:
        try:
            node_path = shutil.which("node")
            version = self._node_version()

            findings: list[Finding] = []
            recommendations: list[str] = []
            status = Status.PASS

            if version:
                findings.append(Finding(summary=f"Node {version}"))
            else:
                findings.append(Finding(summary="Node is on PATH but version could not be read"))
                status = Status.WARN

            manager = self._detect_version_manager(node_path)
            findings.append(Finding(summary=f"Managed by: {manager}"))

            package_manager = self._detect_package_manager()
            if package_manager:
                findings.append(Finding(summary=f"Package manager: {package_manager}"))

            conflicting_managers = self._detect_conflicting_managers()
            if len(conflicting_managers) > 1:
                status = Status.WARN
                findings.append(
                    Finding(
                        summary=f"Multiple Node version managers detected: "
                        f"{', '.join(conflicting_managers)}"
                    )
                )
                recommendations.append(
                    f"Having multiple Node version managers installed "
                    f"({', '.join(conflicting_managers)}) can cause the wrong Node version "
                    f"to be picked up silently depending on shell startup order. Consider "
                    f"standardizing on one."
                )

            return PluginResult(
                plugin_name=self.name,
                status=status,
                score_delta=5 if status == Status.WARN else 0,
                findings=findings,
                recommendations=recommendations,
                metadata={
                    "version": version,
                    "node_path": node_path,
                    "manager": manager,
                    "package_manager": package_manager,
                    "conflicting_managers": conflicting_managers,
                },
            )
        except Exception as e:
            return PluginResult(
                plugin_name=self.name,
                status=Status.FAIL,
                findings=[Finding(summary="Could not run Node diagnostics", detail=str(e))],
            )

    def _node_version(self) -> str | None:
        try:
            result = subprocess.run(
                ["node", "--version"],
                capture_output=True,
                text=True,
                timeout=NODE_TIMEOUT_SECONDS,
            )
            if result.returncode != 0:
                return None
            return result.stdout.strip().lstrip("v") or None
        except (subprocess.SubprocessError, OSError):
            return None

    def _detect_version_manager(self, node_path: str | None) -> str:
        """Infer which tool controls the active `node` on PATH, from its resolved path."""
        if not node_path:
            return "unknown"
        if "/.local/share/mise/" in node_path or "/mise/" in node_path:
            return "mise"
        if "/.nvm/" in node_path:
            return "nvm"
        if "/.volta/" in node_path:
            return "volta"
        if "/.fnm/" in node_path or "/fnm/" in node_path:
            return "fnm"
        if node_path in ("/usr/bin/node", "/usr/local/bin/node"):
            return "system"
        if "/homebrew/" in node_path or "/opt/homebrew/" in node_path:
            return "homebrew"
        return "system"

    def _detect_package_manager(self) -> str | None:
        """Detect the package manager for the current project directory, if any."""
        cwd = Path.cwd()
        lockfiles = {
            "pnpm-lock.yaml": "pnpm",
            "yarn.lock": "yarn",
            "bun.lockb": "bun",
            "package-lock.json": "npm",
        }
        for lockfile, manager in lockfiles.items():
            if (cwd / lockfile).exists():
                return manager
        if (cwd / "package.json").exists():
            return "npm (no lockfile found)"
        return None

    def _detect_conflicting_managers(self) -> list[str]:
        """Check for signs of multiple Node version managers installed at once."""
        found = []
        if (Path.home() / ".nvm").exists():
            found.append("nvm")
        if (Path.home() / ".volta").exists():
            found.append("volta")
        if (Path.home() / ".local" / "share" / "mise").exists() or shutil.which("mise"):
            found.append("mise")
        if (Path.home() / ".fnm").exists():
            found.append("fnm")
        return found