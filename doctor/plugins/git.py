import re

from doctor.capabilities import Capability
from doctor.models import Finding, PluginResult, Status
from doctor.plugins.base import DoctorPlugin
from doctor.services.git_service import GitService

FAIL_SCORE_DELTA = 15
WARN_SCORE_DELTA = 5


class GitPlugin(DoctorPlugin):
    name = "git"
    description = "Checks Git identity, per-repo config, and remote reachability."
    capabilities = [Capability.GIT_REPOSITORY_ACCESS]

    def is_supported(self) -> bool:
        return self.use_service(GitService).is_git_available()

    def run(self) -> PluginResult:
        try:
            git_service = self.use_service(GitService)

            findings: list[Finding] = []
            recommendations: list[str] = []
            status = Status.PASS
            score_delta = 0
            metadata: dict[str, object] = {}

            global_name = git_service.get_global_config("user.name")
            global_email = git_service.get_global_config("user.email")
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

            repo = git_service.find_repo()
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

            local_name, local_email = git_service.get_local_identity(repo)
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

            remote_url = git_service.get_remote_url(repo)
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
                    alias = git_service.find_ssh_alias(host)
                    if alias and alias != host:
                        findings.append(
                            Finding(
                                summary=f"SSH config has an alias '{alias}' for host '{host}', "
                                f"but the remote URL uses the raw hostname directly"
                            )
                        )

            reachable = git_service.check_remote_reachable(remote_url)
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

    def _extract_host(self, remote_url: str) -> str | None:
        """Pull the hostname out of an SSH-shorthand, ssh://, or https:// remote URL."""
        ssh_match = re.match(r"git@([^:]+):", remote_url)
        if ssh_match:
            return ssh_match.group(1)
        url_match = re.match(r"(?:ssh|https?)://(?:[^@]+@)?([^/]+)", remote_url)
        if url_match:
            return url_match.group(1)
        return None