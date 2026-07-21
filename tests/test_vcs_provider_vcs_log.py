"""Integration test for the git ``vcs_log`` hookimpl.

Exercises :class:`BareGitPlugin.vcs_log` (and the delegating
:class:`VCSPluginManager.log`) against a real temporary git repository,
asserting the parsed :class:`VcsCommitWire` fields, newest-first ordering,
merge-commit exclusion, the ``limit`` cap, and multi-line body handling.
"""

from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
import shutil
import subprocess

import pluggy
import pytest

from sase.core.vcs_log_wire import AggregatedCommitWire, VcsCommitWire
from sase.core.vcs_repo_stats_wire import VcsRepoStatsWire
from sase.vcs_log.filter_query import CommitLogFilterValues, compile_commit_matcher
from sase.vcs_log.models import CommitFilters
from sase.vcs_provider._hookspec import VCSHookSpec
from sase.vcs_provider._plugin_manager import VCSPluginManager
from sase.vcs_provider._types import CommandOutput
from sase.vcs_provider.plugins._git_query_ops import (
    GIT_AUTHOR_DATE_UNTIL_SLOP_SECONDS,
)
from sase.vcs_provider.plugins.bare_git import BareGitPlugin

_GIT_AVAILABLE = shutil.which("git") is not None

pytestmark = pytest.mark.skipif(not _GIT_AVAILABLE, reason="git not available")


def _make_git_provider() -> VCSPluginManager:
    pm = pluggy.PluginManager("sase_vcs")
    pm.add_hookspecs(VCSHookSpec)
    pm.register(BareGitPlugin())
    return VCSPluginManager(pm)


def _git(args: list[str], cwd: str, *, env: Mapping[str, str] | None = None) -> None:
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        check=True,
        text=True,
        env=env,
    )


@pytest.fixture()
def repo(tmp_path: Path) -> str:
    cwd = str(tmp_path)
    _git(["init", "-q", "-b", "main"], cwd)
    _git(["config", "user.email", "bryan@example.com"], cwd)
    _git(["config", "user.name", "Bryan"], cwd)
    return cwd


def _commit(
    cwd: str,
    filename: str,
    message: str,
    *,
    timestamp: int | None = None,
    committer_timestamp: int | None = None,
    author_name: str | None = None,
    author_email: str | None = None,
) -> None:
    import os

    (Path(cwd) / filename).write_text("content\n")
    _git(["add", filename], cwd)
    env = os.environ.copy()
    if timestamp is not None:
        raw_date = datetime.fromtimestamp(timestamp, UTC).strftime(
            "%Y-%m-%dT%H:%M:%S %z"
        )
        env["GIT_AUTHOR_DATE"] = raw_date
        if committer_timestamp is None:
            env["GIT_COMMITTER_DATE"] = raw_date
    if committer_timestamp is not None:
        env["GIT_COMMITTER_DATE"] = datetime.fromtimestamp(
            committer_timestamp, UTC
        ).strftime("%Y-%m-%dT%H:%M:%S %z")
    if author_name is not None:
        env["GIT_AUTHOR_NAME"] = author_name
        env["GIT_COMMITTER_NAME"] = author_name
    if author_email is not None:
        env["GIT_AUTHOR_EMAIL"] = author_email
        env["GIT_COMMITTER_EMAIL"] = author_email
    _git(["commit", "-q", "-m", message], cwd, env=env)


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


def test_vcs_log_limit_zero_returns_all_commits(repo: str) -> None:
    for i in range(5):
        _commit(repo, f"f{i}.txt", f"commit {i}")

    commits = BareGitPlugin().vcs_log(repo, 0)

    assert [c.subject for c in commits] == [
        "commit 4",
        "commit 3",
        "commit 2",
        "commit 1",
        "commit 0",
    ]


def test_vcs_log_sloped_until_keeps_margin_for_exact_filter(repo: str) -> None:
    base = 1_700_000_000
    _commit(repo, "a.txt", "old", timestamp=base)
    _commit(repo, "b.txt", "middle", timestamp=base + 1_000)
    _commit(repo, "c.txt", "new", timestamp=base + 2_000)

    commits = BareGitPlugin().vcs_log(repo, 2, since=base + 500, until=base + 1_500)

    assert [c.subject for c in commits] == ["new", "middle"]
    matcher = compile_commit_matcher(
        CommitLogFilterValues(),
        resolved_filters=CommitFilters(since=base + 500, until=base + 1_500),
    )
    entries = tuple(AggregatedCommitWire("repo", commit) for commit in commits)
    assert [entry.commit.subject for entry in entries if matcher(entry)] == ["middle"]


def test_vcs_log_generates_exact_since_and_sloped_until_args(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plugin = BareGitPlugin()
    commands: list[list[str]] = []

    def run(args: list[str], cwd: str) -> CommandOutput:
        del cwd
        commands.append(args)
        return CommandOutput(0, "", "")

    monkeypatch.setattr(plugin, "_run", run)

    assert plugin.vcs_log("/repo", 5, since=100, until=200) == []
    assert len(commands) == 1
    assert commands[0][:-1] == [
        "git",
        "log",
        "-n",
        "5",
        "--no-merges",
        "--since=@100",
        f"--until=@{200 + GIT_AUTHOR_DATE_UNTIL_SLOP_SECONDS}",
        "HEAD",
    ]
    assert commands[0][-1].startswith("--format=")


def test_vcs_log_slop_admits_rebased_author_time_for_exact_match(repo: str) -> None:
    base = 1_700_000_000
    until = base + 12 * 60 * 60
    _commit(
        repo,
        "inside.txt",
        "inside author window",
        timestamp=base,
        committer_timestamp=base + 24 * 60 * 60,
    )
    _commit(
        repo,
        "margin.txt",
        "coarse margin only",
        timestamp=base + 36 * 60 * 60,
        committer_timestamp=base + 48 * 60 * 60,
    )

    commits = BareGitPlugin().vcs_log(repo, 10, until=until)

    assert [commit.subject for commit in commits] == [
        "coarse margin only",
        "inside author window",
    ]
    matcher = compile_commit_matcher(
        CommitLogFilterValues(),
        resolved_filters=CommitFilters(until=until),
    )
    entries = tuple(AggregatedCommitWire("repo", commit) for commit in commits)
    assert [entry.commit.subject for entry in entries if matcher(entry)] == [
        "inside author window"
    ]


def test_vcs_log_author_filter_is_literal_case_insensitive_or(repo: str) -> None:
    base = 1_700_000_000
    _commit(
        repo,
        "a.txt",
        "bryan work",
        timestamp=base,
        author_name="Bryan Bugyi",
        author_email="bryan@example.com",
    )
    _commit(
        repo,
        "b.txt",
        "amy work",
        timestamp=base + 1_000,
        author_name="Amy",
        author_email="amy@example.com",
    )
    _commit(
        repo,
        "c.txt",
        "literal author",
        timestamp=base + 2_000,
        author_name="A.B",
        author_email="literal@example.com",
    )

    plugin = BareGitPlugin()

    assert [c.subject for c in plugin.vcs_log(repo, 10, authors=("BRYAN",))] == [
        "bryan work"
    ]
    assert [c.subject for c in plugin.vcs_log(repo, 10, authors=("bryan", "amy"))] == [
        "amy work",
        "bryan work",
    ]
    assert [c.subject for c in plugin.vcs_log(repo, 10, authors=("A.B",))] == [
        "literal author"
    ]


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


def test_vcs_log_preserves_sase_footer_in_body(repo: str) -> None:
    (Path(repo) / "a.txt").write_text("x\n")
    _git(["add", "a.txt"], repo)
    _git(
        ["commit", "-q", "-m", "subject line", "-m", "body\n\nSASE_TYPE=sdd"],
        repo,
    )

    commit = BareGitPlugin().vcs_log(repo, 10)[0]

    assert commit.subject == "subject line"
    assert "body" in commit.body
    assert "SASE_TYPE=sdd" in commit.body


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


def test_remote_log_ops_fetch_partition_and_union_log(repo: str) -> None:
    provider = BareGitPlugin()
    origin = Path(repo).parent / "origin.git"
    remote_work = Path(repo).parent / "remote-work"

    _commit(repo, "base.txt", "base")
    _git(["init", "--bare", "-q", str(origin)], repo)
    _git(["remote", "add", "origin", str(origin)], repo)
    _git(["push", "-u", "origin", "main"], repo)
    _git(["--git-dir", str(origin), "symbolic-ref", "HEAD", "refs/heads/main"], repo)

    assert provider.vcs_resolve_remote_log_ref(repo) == "origin/main"

    _commit(repo, "local.txt", "local only")
    local_id = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=repo, text=True
    ).strip()

    subprocess.run(
        ["git", "clone", "-q", str(origin), str(remote_work)],
        capture_output=True,
        check=True,
        text=True,
    )
    _git(["config", "user.email", "remote@example.com"], str(remote_work))
    _git(["config", "user.name", "Remote"], str(remote_work))
    _commit(str(remote_work), "remote.txt", "remote only")
    remote_id = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=str(remote_work), text=True
    ).strip()
    _git(["push", "origin", "main"], str(remote_work))

    branch_before = subprocess.check_output(
        ["git", "branch", "--show-current"], cwd=repo, text=True
    ).strip()
    status_before = subprocess.check_output(
        ["git", "status", "--porcelain"], cwd=repo, text=True
    )

    ok, error = provider.vcs_fetch_remote(repo, refs=("origin/main",))
    assert ok is True, error

    branch_after = subprocess.check_output(
        ["git", "branch", "--show-current"], cwd=repo, text=True
    ).strip()
    status_after = subprocess.check_output(
        ["git", "status", "--porcelain"], cwd=repo, text=True
    )
    assert branch_after == branch_before
    assert status_after == status_before

    ahead, behind = provider.vcs_partition_commits(
        repo, local_ref="HEAD", remote_ref="origin/main"
    )
    assert local_id in ahead
    assert remote_id in behind

    subjects = {
        commit.subject
        for commit in provider.vcs_log(repo, 10, revs=("HEAD", "origin/main"))
    }
    assert {"base", "local only", "remote only"} <= subjects


def test_remote_log_ref_returns_none_without_origin(repo: str) -> None:
    assert BareGitPlugin().vcs_resolve_remote_log_ref(repo) is None


def test_vcs_log_empty_repo_returns_empty(repo: str) -> None:
    # A repo with no commits: `git log` fails (no HEAD); the hook surfaces
    # that as a VCSOperationError rather than a silent empty list.
    from sase.vcs_provider import VCSOperationError

    with pytest.raises(VCSOperationError):
        BareGitPlugin().vcs_log(repo, 10)


def test_vcs_repo_stats_empty_repo_returns_zero(repo: str) -> None:
    stats = BareGitPlugin().vcs_repo_stats(repo)

    assert stats == VcsRepoStatsWire(
        total_commits=0,
        contributors=(),
        last_commit=None,
        branch=None,
        dirty=False,
    )


def test_vcs_repo_stats_collects_counts_branch_dirty_and_last_commit(
    repo: str,
) -> None:
    _commit(
        repo,
        "a.txt",
        "first",
        timestamp=1_700_000_000,
        author_name="Bryan",
        author_email="bryan@example.com",
    )
    _commit(
        repo,
        "b.txt",
        "second",
        timestamp=1_700_001_000,
        author_name="Amy",
        author_email="amy@example.com",
    )
    (Path(repo) / "dirty.txt").write_text("dirty\n")

    stats = BareGitPlugin().vcs_repo_stats(repo)

    assert stats.total_commits == 2
    assert stats.contributors == (
        "Amy <amy@example.com>",
        "Bryan <bryan@example.com>",
    )
    assert stats.branch == "main"
    assert stats.dirty is True
    assert stats.last_commit is not None
    assert stats.last_commit.subject == "second"
    assert stats.last_commit.author_name == "Amy"


def test_provider_log_delegates_to_hook(repo: str) -> None:
    _commit(repo, "a.txt", "only commit")

    provider = _make_git_provider()
    commits = provider.log(cwd=repo, limit=10, authors=("bryan",))

    assert [c.subject for c in commits] == ["only commit"]


def test_provider_repo_stats_delegates_to_hook(repo: str) -> None:
    _commit(repo, "a.txt", "only commit")

    provider = _make_git_provider()
    stats = provider.repo_stats(cwd=repo)

    assert stats.total_commits == 1
    assert stats.last_commit is not None
    assert stats.last_commit.subject == "only commit"
