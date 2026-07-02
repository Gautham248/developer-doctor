from unittest.mock import MagicMock, patch

from git import InvalidGitRepositoryError

from doctor.services.git_service import GitService


def test_is_git_available_true_when_version_succeeds():
    service = GitService()
    with patch("doctor.services.git_service.git_module.Git") as mock_git_cls:
        mock_git_cls.return_value.version.return_value = "git version 2.4"
        assert service.is_git_available() is True


def test_is_git_available_false_on_exception():
    service = GitService()
    with patch("doctor.services.git_service.git_module.Git", side_effect=Exception("boom")):
        assert service.is_git_available() is False


def test_get_global_config_returns_stripped_value():
    service = GitService()
    with patch("doctor.services.git_service.git_module.Git") as mock_git_cls:
        mock_git_cls.return_value.config.return_value = "  Gautham  "
        assert service.get_global_config("user.name") == "Gautham"


def test_get_global_config_returns_none_on_command_error():
    from git import GitCommandError

    service = GitService()
    with patch("doctor.services.git_service.git_module.Git") as mock_git_cls:
        mock_git_cls.return_value.config.side_effect = GitCommandError("config", 1)
        assert service.get_global_config("user.name") is None


def test_find_repo_returns_none_outside_repo(tmp_path):
    service = GitService()
    with patch("doctor.services.git_service.Repo", side_effect=InvalidGitRepositoryError):
        assert service.find_repo(start=tmp_path) is None


def test_find_repo_returns_repo_instance(tmp_path):
    service = GitService()
    fake_repo = MagicMock()
    with patch("doctor.services.git_service.Repo", return_value=fake_repo):
        assert service.find_repo(start=tmp_path) is fake_repo


def test_get_local_identity_returns_values_from_config_reader():
    service = GitService()
    fake_repo = MagicMock()
    fake_reader = MagicMock()
    fake_reader.get_value.side_effect = lambda section, key, default=None: {
        ("user", "name"): "Work Name",
        ("user", "email"): "work@company.com",
    }.get((section, key), default)
    fake_repo.config_reader.return_value = fake_reader

    name, email = service.get_local_identity(fake_repo)
    assert name == "Work Name"
    assert email == "work@company.com"


def test_get_remote_url_returns_url():
    service = GitService()
    fake_repo = MagicMock()
    fake_repo.remotes.origin.url = "git@github.com:org/repo.git"
    assert service.get_remote_url(fake_repo) == "git@github.com:org/repo.git"


def test_get_remote_url_returns_none_on_missing_origin():
    service = GitService()
    fake_repo = MagicMock(spec=[])
    assert service.get_remote_url(fake_repo) is None


def test_find_ssh_alias_matches_hostname(tmp_path):
    ssh_dir = tmp_path / ".ssh"
    ssh_dir.mkdir()
    (ssh_dir / "config").write_text("Host github.com-personal\n  HostName github.com\n  User git\n")

    service = GitService()
    with patch("pathlib.Path.home", return_value=tmp_path):
        assert service.find_ssh_alias("github.com") == "github.com-personal"


def test_find_ssh_alias_returns_none_when_no_config(tmp_path):
    service = GitService()
    with patch("pathlib.Path.home", return_value=tmp_path):
        assert service.find_ssh_alias("github.com") is None


def test_check_remote_reachable_true_on_zero_exit():
    service = GitService()
    mock_result = MagicMock(returncode=0)
    with patch("subprocess.run", return_value=mock_result):
        assert service.check_remote_reachable("git@github.com:org/repo.git") is True


def test_check_remote_reachable_false_on_nonzero_exit():
    service = GitService()
    mock_result = MagicMock(returncode=1)
    with patch("subprocess.run", return_value=mock_result):
        assert service.check_remote_reachable("git@github.com:org/repo.git") is False


def test_check_remote_reachable_none_on_subprocess_error():
    import subprocess as sp

    service = GitService()
    with patch("subprocess.run", side_effect=sp.TimeoutExpired(cmd="git", timeout=5)):
        assert service.check_remote_reachable("git@github.com:org/repo.git") is None