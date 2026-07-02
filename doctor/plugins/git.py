import re
import subprocess
from pathlib import Path

import git
from git import GitCommandError, InvalidGitRepositoryError, Repo

from doctor.models import Finding, PluginResult, Status
from doctor.plugins.base import DoctorPlugin
from doctor.capabilities import Capability

FAIL_SCORE_DELTA = 15
WARN_SCORE_DELTA = 5
REMOTE_CHECK_TIMEOUT_SECONDS = 5


class GitPlugin(DoctorPlugin):
    name = "git"
    description = "Checks Git identity, per-repo config, and remote reachability."
    capabilities = [
        Capability.GIT_REPOSITORY_ACCESS,
        Capability.FILESYSTEM_READ,
        Capability.SHELL_COMMANDS,
        Capability.NETWORK_SOCKETS,
    ]
    def is_supported(self) -> bool:
        try:
            git.Git().version()
            return True
        except Exception:
            return False

    def run(self) -> PluginResult:
        try:
            findings: list[Finding] = []
            recommendations: list[str] = []
            status = Status.PASS
            score_delta = 0
            metadata: dict[str, object] = {}

            global_name = self._git_config_global("user.name")
            global_email = self._git_config_global("user.email")
            metadata["global_name"] = global_name
            metadata["global_email"] = global_email

            if not global_name or not global_email:
                status = Status.FAIL
                score_delta = FAIL_SCORE_DELTA
                findings.append(Finding(summary="Global Git identity is not fully configured"))
                recommendations.append(
                    'Set your global Git identity: git config --global user.name "Your Name" '
                    'and git config --global user.email "you@example.com".'
                )
            else:
                findings.append(Finding(summary=f"Global identity: {global_name} <{global_email}>"))

            repo = self._find_repo()
            if repo is None:
                findings.append(Finding(summary="Not inside a Git repository"))
                return PluginResult(
                    plugin_name=self.name,
                    status=status,
                    score_delta=score_delta,
                    findings=findings,
                    recommendations=recommendations,
                    metadata=metadata,
                )

            local_name, local_email = self._local_identity(repo)
            metadata["local_name"] = local_name
            metadata["local_email"] = local_email

            if local_name or local_email:
                findings.append(
                    Finding(
                        summary=f"Repo-local identity override: "
                        f"{local_name or global_name} <{local_email or global_email}>"
                    )
                )
            elif not global_name or not global_email:
                recommendations.append(
                    "This repo has no local Git identity override either — commits here "
                    "will fail without a global identity set."
                )

            remote_url = self._remote_url(repo)
            if remote_url is None:
                findings.append(Finding(summary="No 'origin' remote configured"))
                return PluginResult(
                    plugin_name=self.name,
                    status=status,
                    score_delta=score_delta,
                    findings=findings,
                    recommendations=recommendations,
                    metadata=metadata,
                )

            findings.append(Finding(summary=f"Remote: {remote_url}"))
            metadata["remote_url"] = remote_url

            host = self._extract_host(remote_url)
            if host:
                metadata["remote_host"] = host
                if remote_url.startswith("git@") or "ssh://" in remote_url:
                    alias = self._matching_ssh_alias(host)
                    if alias and alias != host:
                        findings.append(
                            Finding(
                                summary=f"SSH config has an alias '{alias}' for host '{host}', "
                                f"but the remote URL uses the raw hostname directly"
                            )
                        )

            reachable = self._check_remote_reachable(remote_url)
            if reachable is False:
                if status == Status.PASS:
                    status = Status.WARN
                score_delta = max(score_delta, WARN_SCORE_DELTA)
                findings.append(Finding(summary="Remote is not reachable"))
                recommendations.append(
                    "Could not reach the 'origin' remote. Check your network connection, "
                    "VPN, or SSH/HTTPS credentials for this repository."
                )
            elif reachable is True:
                findings.append(Finding(summary="Remote is reachable"))
            # reachable is None: check couldn't run (e.g. git binary issue) — inconclusive, say nothing.

            return PluginResult(
                plugin_name=self.name,
                status=status,
                score_delta=score_delta,
                findings=findings,
                recommendations=recommendations,
                metadata=metadata,
            )
        except Exception as e:
            return PluginResult(
                plugin_name=self.name,
                status=Status.FAIL,
                findings=[Finding(summary="Could not run Git diagnostics", detail=str(e))],
            )

    def _git_config_global(self, key: str) -> str | None:
        try:
            value = git.Git().config("--global", "--get", key)
            return value.strip() or None
        except GitCommandError:
            return None

    def _find_repo(self) -> Repo | None:
        try:
            return Repo(Path.cwd(), search_parent_directories=True)
        except InvalidGitRepositoryError:
            return None

    def _local_identity(self, repo: Repo) -> tuple[str | None, str | None]:
        try:
            reader = repo.config_reader(config_level="repository")
            name = reader.get_value("user", "name", default=None)
            email = reader.get_value("user", "email", default=None)
            return (str(name) if name else None, str(email) if email else None)
        except Exception:
            return None, None

    def _remote_url(self, repo: Repo) -> str | None:
        try:
            return repo.remotes.origin.url
        except (AttributeError, ValueError):
            return None

    def _extract_host(self, remote_url: str) -> str | None:
        """Pull the hostname out of an SSH-shorthand, ssh://, or https:// remote URL."""
        ssh_match = re.match(r"git@([^:]+):", remote_url)
        if ssh_match:
            return ssh_match.group(1)
        url_match = re.match(r"(?:ssh|https?)://(?:[^@]+@)?([^/]+)", remote_url)
        if url_match:
            return url_match.group(1)
        return None

    def _matching_ssh_alias(self, host: str) -> str | None:
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

    def _check_remote_reachable(self, remote_url: str) -> bool | None:
        """Best-effort reachability check via `git ls-remote`.

        Returns True/False if the check completed, or None if it couldn't
        run at all — callers must treat None as inconclusive, never as a
        failure signal.
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