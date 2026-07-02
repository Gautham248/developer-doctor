import subprocess
from pathlib import Path

import git as git_module
from git import GitCommandError, InvalidGitRepositoryError, Repo

from doctor.capabilities import Capability
from doctor.services.base import BaseService

REMOTE_CHECK_TIMEOUT_SECONDS = 5


class GitService(BaseService):
    """Shared, testable interface to Git identity, repo, and remote state.

    Consolidates git.Git()/GitPython/subprocess calls previously embedded
    directly in GitPlugin.
    """

    required_capability = Capability.GIT_REPOSITORY_ACCESS

    def is_git_available(self) -> bool:
        try:
            git_module.Git().version()
            return True
        except Exception:
            return False

    def get_global_config(self, key: str) -> str | None:
        try:
            value = git_module.Git().config("--global", "--get", key)
            return value.strip() or None
        except GitCommandError:
            return None

    def find_repo(self, start: Path | None = None) -> Repo | None:
        try:
            return Repo(start or Path.cwd(), search_parent_directories=True)
        except InvalidGitRepositoryError:
            return None

    def get_local_identity(self, repo: Repo) -> tuple[str | None, str | None]:
        try:
            reader = repo.config_reader(config_level="repository")
            name = reader.get_value("user", "name", default=None)
            email = reader.get_value("user", "email", default=None)
            return (str(name) if name else None, str(email) if email else None)
        except Exception:
            return None, None

    def get_remote_url(self, repo: Repo) -> str | None:
        try:
            return repo.remotes.origin.url
        except (AttributeError, ValueError):
            return None

    def find_ssh_alias(self, host: str) -> str | None:
        """Look for a Host entry in ~/.ssh/config whose HostName matches the given host."""
        ssh_config_path = Path.home() / ".ssh" / "config"
        if not ssh_config_path.exists():
            return None
        try:
            content = ssh_config_path.read_text()
        except OSError:
            return None

        current_alias: str | None = None
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.lower().startswith("host "):
                current_alias = stripped.split(None, 1)[1].strip()
            elif stripped.lower().startswith("hostname ") and current_alias:
                hostname = stripped.split(None, 1)[1].strip()
                if hostname == host:
                    return current_alias
        return None

    def check_remote_reachable(self, remote_url: str) -> bool | None:
        """Best-effort reachability check via `git ls-remote`.

        Returns True/False if the check completed, or None if it couldn't
        run at all — callers must treat None as inconclusive, never as
        a failure signal.
        """
        try:
            result = subprocess.run(
                ["git", "ls-remote", "--exit-code", remote_url, "HEAD"],
                capture_output=True,
                timeout=REMOTE_CHECK_TIMEOUT_SECONDS,
            )
            return result.returncode == 0
        except (subprocess.SubprocessError, OSError):
            return None