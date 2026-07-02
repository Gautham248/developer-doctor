from unittest.mock import patch

from doctor.models import Status
from doctor.plugins.git import GitPlugin
from doctor.services.git_service import GitService


def test_extract_host_from_ssh_shorthand():
    plugin = GitPlugin()
    assert plugin._extract_host("git@github.com:org/repo.git") == "github.com"


def test_extract_host_from_https():
    plugin = GitPlugin()
    assert plugin._extract_host("https://github.com/org/repo.git") == "github.com"


def test_extract_host_from_ssh_url():
    plugin = GitPlugin()
    assert plugin._extract_host("ssh://git@gitlab.company.com/org/repo.git") == "gitlab.company.com"


def test_git_plugin_fails_without_global_identity():
    plugin = GitPlugin()
    with (
        patch.object(GitService, "get_global_config", return_value=None),
        patch.object(GitService, "find_repo", return_value=None),
    ):
        result = plugin.run()

    assert result.status == Status.FAIL
    assert result.score_delta == 15


def test_git_plugin_passes_with_identity_and_no_repo():
    plugin = GitPlugin()

    def fake_config(self, key: str) -> str | None:
        return {"user.name": "Gautham", "user.email": "g@example.com"}[key]

    with (
        patch.object(GitService, "get_global_config", fake_config),
        patch.object(GitService, "find_repo", return_value=None),
    ):
        result = plugin.run()

    assert result.status == Status.PASS
    assert result.score_delta == 0
    assert any("Not inside a Git repository" in f.summary for f in result.findings)


def test_git_plugin_warns_on_unreachable_remote():
    plugin = GitPlugin()
    fake_repo = object()

    def fake_config(self, key: str) -> str | None:
        return {"user.name": "Gautham", "user.email": "g@example.com"}[key]

    with (
        patch.object(GitService, "get_global_config", fake_config),
        patch.object(GitService, "find_repo", return_value=fake_repo),
        patch.object(GitService, "get_local_identity", return_value=(None, None)),
        patch.object(GitService, "get_remote_url", return_value="git@github.com:org/repo.git"),
        patch.object(GitService, "find_ssh_alias", return_value=None),
        patch.object(GitService, "check_remote_reachable", return_value=False),
    ):
        result = plugin.run()

    assert result.status == Status.WARN
    assert result.score_delta == 5
    assert any("not reachable" in f.summary.lower() for f in result.findings)


def test_git_plugin_reports_repo_local_override_and_reachable_remote():
    plugin = GitPlugin()
    fake_repo = object()

    def fake_config(self, key: str) -> str | None:
        return {"user.name": "Gautham", "user.email": "personal@example.com"}[key]

    with (
        patch.object(GitService, "get_global_config", fake_config),
        patch.object(GitService, "find_repo", return_value=fake_repo),
        patch.object(GitService, "get_local_identity", return_value=("Gautham", "work@company.com")),
        patch.object(GitService, "get_remote_url", return_value="https://github.com/org/repo.git"),
        patch.object(GitService, "find_ssh_alias", return_value=None),
        patch.object(GitService, "check_remote_reachable", return_value=True),
    ):
        result = plugin.run()

    assert result.status == Status.PASS
    assert any("work@company.com" in f.summary for f in result.findings)
    assert any("Remote is reachable" in f.summary for f in result.findings)


def test_git_plugin_never_raises_on_unexpected_failure():
    plugin = GitPlugin()
    with patch.object(GitService, "get_global_config", side_effect=RuntimeError("boom")):
        result = plugin.run()

    assert result.status == Status.FAIL
    assert "Could not run Git diagnostics" in result.findings[0].summary