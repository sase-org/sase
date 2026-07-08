"""Integration test for the git ``vcs_log`` hookimpl.

Exercises :class:`BareGitPlugin.vcs_log` (and the delegating
:class:`VCSPluginManager.log`) against a real temporary git repository,
asserting the parsed :class:`VcsCommitWire` fields, newest-first ordering,
merge-commit exclusion, the ``limit`` cap, and multi-line body handling.
"""

import shutil
import subprocess
from pathlib import Path

import pluggy
import pytest

from sase.core.vcs_log_wire import VcsCommitWire
from sase.vcs_provider._hookspec import VCSHookSpec
from sase.vcs_provider._plugin_manager import VCSPluginManager
from sase.vcs_provider.plugins.bare_git import BareGitPlugin

_GIT_AVAILABLE = shutil.which("git") is not None

pytestmark = pytest.mark.skipif(not _GIT_AVAILABLE, reason="git not available")


def _make_git_provider() -> VCSPluginManager:
    pm = pluggy.PluginManager("sase_vcs")
    pm.add_hookspecs(VCSHookSpec)
    pm.register(BareGitPlugin())
    return VCSPluginManager(pm)


def _git(args: list[str], cwd: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, capture_output=True, check=True, text=True)


@pytest.fixture()
def repo(tmp_path: Path) -> str:
    cwd = str(tmp_path)
    _git(["init", "-q", "-b", "main"], cwd)
    _git(["config", "user.email", "bryan@example.com"], cwd)
    _git(["config", "user.name", "Bryan"], cwd)
    return cwd


def _commit(cwd: str, filename: str, message: str) -> None:
    (Path(cwd) / filename).write_text("content\n")
    _git(["add", filename], cwd)
    _git(["commit", "-q", "-m", message], cwd)


def test_vcs_log_parses_commit_fields(repo: str) -> None:
    _commit(repo, "a.txt", "feat: first commit")

    commits = BareGitPlugin().vcs_log(repo, 10)

    assert len(commits) == 1
    commit = commits[0]
    assert isinstance(commit, VcsCommitWire)
    assert commit.subject == "feat: first commit"
    assert commit.author_name == "Bryan"
    assert commit.author_email == "bryan@example.com"
    assert commit.timestamp > 0
    # Short id is a prefix of the full id.
    assert commit.full_id.startswith(commit.short_id)
    assert len(commit.short_id) < len(commit.full_id)


def test_vcs_log_orders_newest_first(repo: str) -> None:
    _commit(repo, "a.txt", "first")
    _commit(repo, "b.txt", "second")
    _commit(repo, "c.txt", "third")

    subjects = [c.subject for c in BareGitPlugin().vcs_log(repo, 10)]

    assert subjects == ["third", "second", "first"]


def test_vcs_log_respects_limit(repo: str) -> None:
    for i in range(5):
        _commit(repo, f"f{i}.txt", f"commit {i}")

    commits = BareGitPlugin().vcs_log(repo, 2)

    assert [c.subject for c in commits] == ["commit 4", "commit 3"]


def test_vcs_log_preserves_multiline_body(repo: str) -> None:
    (Path(repo) / "a.txt").write_text("x\n")
    _git(["add", "a.txt"], repo)
    _git(
        ["commit", "-q", "-m", "subject line", "-m", "body one\nbody two"],
        repo,
    )

    commit = BareGitPlugin().vcs_log(repo, 10)[0]

    assert commit.subject == "subject line"
    assert "body one" in commit.body
    assert "body two" in commit.body


def test_vcs_log_excludes_merge_commits(repo: str) -> None:
    _commit(repo, "base.txt", "base")
    _git(["checkout", "-q", "-b", "feature"], repo)
    _commit(repo, "feature.txt", "feature work")
    _git(["checkout", "-q", "main"], repo)
    _commit(repo, "main.txt", "main work")
    _git(["merge", "--no-ff", "-q", "-m", "merge feature", "feature"], repo)

    subjects = [c.subject for c in BareGitPlugin().vcs_log(repo, 10)]

    assert "merge feature" not in subjects
    assert {"base", "feature work", "main work"} == set(subjects)


def test_vcs_log_empty_repo_returns_empty(repo: str) -> None:
    # A repo with no commits: `git log` fails (no HEAD); the hook surfaces
    # that as a VCSOperationError rather than a silent empty list.
    from sase.vcs_provider import VCSOperationError

    with pytest.raises(VCSOperationError):
        BareGitPlugin().vcs_log(repo, 10)


def test_provider_log_delegates_to_hook(repo: str) -> None:
    _commit(repo, "a.txt", "only commit")

    provider = _make_git_provider()
    commits = provider.log(cwd=repo, limit=10)

    assert [c.subject for c in commits] == ["only commit"]
