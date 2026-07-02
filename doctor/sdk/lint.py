import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

LINT_TIMEOUT_SECONDS = 60


@dataclass
class ToolResult:
    tool: str
    ran: bool
    passed: bool
    output: str


@dataclass
class LintResult:
    results: list[ToolResult]

    @property
    def passed(self) -> bool:
        """Only tools that actually ran count towards pass/fail — a
        skipped tool (not installed) doesn't fail lint, since a
        third-party plugin author may not have every dev tool
        available locally."""
        ran_results = [r for r in self.results if r.ran]
        return all(r.passed for r in ran_results)


def lint_plugin(path: Path) -> LintResult:
    """Run ruff and mypy against a plugin file or directory (§22.5's
    `doctor plugin lint`)."""
    results = [
        _run_tool("ruff", ["ruff", "check", str(path)]),
        _run_tool("mypy", ["mypy", "--ignore-missing-imports", str(path)]),
    ]
    return LintResult(results=results)


def _run_tool(name: str, command: list[str]) -> ToolResult:
    if shutil.which(command[0]) is None:
        return ToolResult(tool=name, ran=False, passed=True, output=f"{name} not installed, skipped.")
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=LINT_TIMEOUT_SECONDS,
        )
        output = (result.stdout + result.stderr).strip()
        return ToolResult(tool=name, ran=True, passed=result.returncode == 0, output=output)
    except (subprocess.SubprocessError, OSError) as e:
        return ToolResult(tool=name, ran=True, passed=False, output=f"Failed to run {name}: {e}")