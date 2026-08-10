"""Integration test for the git ``vcs_log`` hookimpl.

Exercises :class:`BareGitPlugin.vcs_log` (and the delegating
:class:`VCSPluginManager.log`) against a real temporary git repository,
asserting the parsed :class:`VcsCommitWire` fields, newest-first ordering,
merge-commit visibility, the ``limit`` cap, and multi-line body handling.
"""

from collections.abc import Mapping
from datetime import UTC, datetime
import os
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
from sase.vcs_provider._types import CommandOutput, MergeVisibility
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


def _plugin_log(
    plugin: BareGitPlugin,
    cwd: str,
    limit: int,
    *,
    since: int | None = None,
    until: int | None = None,
    authors: tuple[str, ...] = (),
    revs: tuple[str, ...] = ("HEAD",),
    merges: MergeVisibility = "hide",
) -> list[VcsCommitWire]:
    return plugin.vcs_log(cwd, limit, since, until, authors, revs, merges)


def _bare_git_log(
    cwd: str,
    limit: int,
    *,
    since: int | None = None,
    until: int | None = None,
    authors: tuple[str, ...] = (),
    revs: tuple[str, ...] = ("HEAD",),
    merges: MergeVisibility = "hide",
) -> list[VcsCommitWire]:
    return _plugin_log(
        BareGitPlugin(),
        cwd,
        limit,
        since=since,
        until=until,
        authors=authors,
        revs=revs,
        merges=merges,
    )


def _git_env(extra: Mapping[str, str] | None = None) -> dict[str, str]:
    env = {
        key: value for key, value in os.environ.items() if not key.startswith("GIT_")
    }
    if extra:
        env.update(extra)
    return env


def _git(args: list[str], cwd: str, *, env: Mapping[str, str] | None = None) -> None:
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        check=True,
        text=True,
        env=_git_env(env),
    )


def _git_stdout(args: list[str], cwd: str) -> str:
    return subprocess.check_output(["git", *args], cwd=cwd, text=True, env=_git_env())


def _rev_parse(cwd: str, rev: str = "HEAD") -> str:
    return _git_stdout(["rev-parse", rev], cwd).strip()


@pytest.fixture(autouse=True)
def clean_git_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in tuple(os.environ):
        if key.startswith("GIT_"):
            monkeypatch.delenv(key, raising=False)


@pytest.fixture()
def repo(tmp_path: Path) -> str:
    cwd = str(tmp_path)
    _git(["init", "-q", "-b", "main"], cwd)
    _git(["config", "user.email", "bryan@example.com"], cwd)
    _git(["config", "user.name", "Bryan"], cwd)
    return cwd


@pytest.fixture()
def remote_repo(repo: str) -> Path:
    # `tmp_path.parent` is the pytest basetemp shared by every test in the
    # worker, so a literal sibling name here would collide with another
    # test's remote. `tmp_path` itself is unique per test, so deriving the
    # name from it keeps this path unique without a global counter.
    return Path(repo).parent / f"{Path(repo).name}-origin.git"


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
    (Path(cwd) / filename).write_text("content\n")
    _git(["add", filename], cwd)
    env: dict[str, str] = {}
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


def _make_merge_history(repo: str) -> dict[str, str]:
    _commit(repo, "base.txt", "base")
    base_id = _rev_parse(repo)
    _git(["checkout", "-q", "-b", "feature"], repo)
    _commit(repo, "feature.txt", "feature work")
    feature_id = _rev_parse(repo)
    _git(["checkout", "-q", "main"], repo)
    _commit(repo, "main.txt", "main work")
    main_id = _rev_parse(repo)
    _git(["merge", "--no-ff", "-q", "-m", "merge feature", "feature"], repo)
    merge_id = _rev_parse(repo)
    return {
        "base": base_id,
        "feature work": feature_id,
        "main work": main_id,
        "merge feature": merge_id,
    }


def test_vcs_log_parses_commit_fields(repo: str) -> None:
    _commit(repo, "a.txt", "feat: first commit")

    commits = _bare_git_log(repo, 10)

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
    assert commit.parent_ids == ()
    assert commit.is_merge is False


def test_vcs_log_orders_newest_first(repo: str) -> None:
    _commit(repo, "a.txt", "first")
    _commit(repo, "b.txt", "second")
    _commit(repo, "c.txt", "third")

    subjects = [c.subject for c in _bare_git_log(repo, 10)]

    assert subjects == ["third", "second", "first"]


def test_vcs_log_respects_limit(repo: str) -> None:
    for i in range(5):
        _commit(repo, f"f{i}.txt", f"commit {i}")

    commits = _bare_git_log(repo, 2)

    assert [c.subject for c in commits] == ["commit 4", "commit 3"]


def test_vcs_log_limit_zero_returns_all_commits(repo: str) -> None:
    for i in range(5):
        _commit(repo, f"f{i}.txt", f"commit {i}")

    commits = _bare_git_log(repo, 0)

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

    commits = _bare_git_log(repo, 2, since=base + 500, until=base + 1_500)

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

    assert _plugin_log(plugin, "/repo", 5, since=100, until=200) == []
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


@pytest.mark.parametrize(
    ("merges", "expected_args"),
    [
        ("hide", ["git", "log", "-n", "5", "--no-merges", "HEAD"]),
        ("show", ["git", "log", "-n", "5", "HEAD"]),
        ("only", ["git", "log", "-n", "5", "--merges", "HEAD"]),
    ],
)
def test_vcs_log_generates_merge_visibility_args(
    monkeypatch: pytest.MonkeyPatch,
    merges: MergeVisibility,
    expected_args: list[str],
) -> None:
    plugin = BareGitPlugin()
    commands: list[list[str]] = []

    def run(args: list[str], cwd: str) -> CommandOutput:
        del cwd
        commands.append(args)
        return CommandOutput(0, "", "")

    monkeypatch.setattr(plugin, "_run", run)

    assert _plugin_log(plugin, "/repo", 5, merges=merges) == []

    assert len(commands) == 1
    assert commands[0][:-1] == expected_args
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

    commits = _bare_git_log(repo, 10, until=until)

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

    provider = _make_git_provider()

    assert [c.subject for c in provider.log(repo, 10, authors=("BRYAN",))] == [
        "bryan work"
    ]
    assert [c.subject for c in provider.log(repo, 10, authors=("bryan", "amy"))] == [
        "amy work",
        "bryan work",
    ]
    assert [c.subject for c in provider.log(repo, 10, authors=("A.B",))] == [
        "literal author"
    ]
    assert provider.log(repo, 10, authors=("nobody-matches-this",)) == []


def test_provider_log_delegates_time_filters_to_hook(repo: str) -> None:
    base = 1_700_000_000
    _commit(repo, "a.txt", "old", timestamp=base)
    _commit(repo, "b.txt", "recent", timestamp=base + 1_000)
    provider = _make_git_provider()

    assert provider.log(repo, 10, since=base + 10_000) == []
    assert (
        provider.log(
            repo,
            10,
            until=base - GIT_AUTHOR_DATE_UNTIL_SLOP_SECONDS - 100,
        )
        == []
    )


def test_vcs_log_preserves_multiline_body(repo: str) -> None:
    (Path(repo) / "a.txt").write_text("x\n")
    _git(["add", "a.txt"], repo)
    _git(
        ["commit", "-q", "-m", "subject line", "-m", "body one\nbody two"],
        repo,
    )

    commit = _bare_git_log(repo, 10)[0]

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

    commit = _bare_git_log(repo, 10)[0]

    assert commit.subject == "subject line"
    assert "body" in commit.body
    assert "SASE_TYPE=sdd" in commit.body


@pytest.mark.parametrize(
    ("merges", "expected_subjects"),
    [
        ("hide", {"base", "feature work", "main work"}),
        ("show", {"base", "feature work", "main work", "merge feature"}),
        ("only", {"merge feature"}),
    ],
)
def test_vcs_log_merge_visibility_modes(
    repo: str, merges: MergeVisibility, expected_subjects: set[str]
) -> None:
    _make_merge_history(repo)

    provider = _make_git_provider()
    subjects = {c.subject for c in provider.log(repo, 10, merges=merges)}

    assert subjects == expected_subjects


def test_vcs_log_merge_visibility_partition_law(repo: str) -> None:
    _make_merge_history(repo)
    provider = _make_git_provider()

    hide_ids = {c.full_id for c in provider.log(repo, 10, merges="hide")}
    show_ids = {c.full_id for c in provider.log(repo, 10, merges="show")}
    only_ids = {c.full_id for c in provider.log(repo, 10, merges="only")}

    assert hide_ids.isdisjoint(only_ids)
    assert hide_ids | only_ids == show_ids


def test_vcs_log_populates_parent_ids(repo: str) -> None:
    expected_ids = _make_merge_history(repo)

    commits = {
        commit.subject: commit
        for commit in _make_git_provider().log(repo, 10, merges="show")
    }

    assert commits["base"].parent_ids == ()
    assert commits["base"].is_merge is False
    assert commits["feature work"].parent_ids == (expected_ids["base"],)
    assert commits["main work"].parent_ids == (expected_ids["base"],)
    assert commits["merge feature"].parent_ids == (
        expected_ids["main work"],
        expected_ids["feature work"],
    )
    assert commits["merge feature"].is_merge is True


def test_vcs_show_revision_ordinary_commit_matches_default_git_show(repo: str) -> None:
    _commit(repo, "ordinary.txt", "ordinary")
    commit_id = _rev_parse(repo)

    ok, output = BareGitPlugin().vcs_show_revision(commit_id, repo)
    expected = _git_stdout(["show", "--format=", "--patch", commit_id], repo)

    assert ok is True
    assert output == expected


def test_vcs_show_revision_merge_commit_returns_first_parent_patch(repo: str) -> None:
    ids = _make_merge_history(repo)
    merge_id = ids["merge feature"]

    ok, output = BareGitPlugin().vcs_show_revision(merge_id, repo)
    expected = _git_stdout(
        ["show", "--first-parent", "--format=", "--patch", merge_id], repo
    )

    assert ok is True
    assert output == expected
    assert output is not None
    assert output.strip()
    assert "feature.txt" in output


def test_vcs_partition_commits_honors_merge_visibility_modes(
    repo: str, remote_repo: Path
) -> None:
    provider = _make_git_provider()
    origin = remote_repo

    _commit(repo, "base.txt", "base")
    _git(["init", "--bare", "-q", str(origin)], repo)
    _git(["remote", "add", "origin", str(origin)], repo)
    _git(["push", "-u", "origin", "main"], repo)
    _git(["--git-dir", str(origin), "symbolic-ref", "HEAD", "refs/heads/main"], repo)

    _git(["checkout", "-q", "-b", "feature"], repo)
    _commit(repo, "feature.txt", "feature work")
    feature_id = _rev_parse(repo)
    _git(["checkout", "-q", "main"], repo)
    _git(["merge", "--no-ff", "-q", "-m", "merge feature", "feature"], repo)
    merge_id = _rev_parse(repo)

    hide_ahead, hide_behind = provider.partition_commits(
        repo, local_ref="HEAD", remote_ref="origin/main", merges="hide"
    )
    show_ahead, show_behind = provider.partition_commits(
        repo, local_ref="HEAD", remote_ref="origin/main", merges="show"
    )
    only_ahead, only_behind = provider.partition_commits(
        repo, local_ref="HEAD", remote_ref="origin/main", merges="only"
    )

    assert hide_ahead == {feature_id}
    assert show_ahead == {feature_id, merge_id}
    assert only_ahead == {merge_id}
    assert hide_behind == set()
    assert show_behind == set()
    assert only_behind == set()


def test_remote_log_ops_fetch_partition_and_union_log(
    repo: str, remote_repo: Path
) -> None:
    provider = _make_git_provider()
    origin = remote_repo
    remote_work = Path(repo).parent / f"{Path(repo).name}-remote-work"

    _commit(repo, "base.txt", "base")
    _git(["init", "--bare", "-q", str(origin)], repo)
    _git(["remote", "add", "origin", str(origin)], repo)
    _git(["push", "-u", "origin", "main"], repo)
    _git(["--git-dir", str(origin), "symbolic-ref", "HEAD", "refs/heads/main"], repo)

    assert provider.resolve_remote_log_ref(repo) == "origin/main"
    assert provider.resolve_remote_log_ref(repo, ref_name="feature") == "origin/feature"

    _commit(repo, "local.txt", "local only")
    local_id = _rev_parse(repo)

    _git(["clone", "-q", str(origin), str(remote_work)], str(Path(repo).parent))
    _git(["config", "user.email", "remote@example.com"], str(remote_work))
    _git(["config", "user.name", "Remote"], str(remote_work))
    _commit(str(remote_work), "remote.txt", "remote only")
    remote_id = _rev_parse(str(remote_work))
    _git(["push", "origin", "main"], str(remote_work))

    branch_before = _git_stdout(["branch", "--show-current"], repo).strip()
    status_before = _git_stdout(["status", "--porcelain"], repo)

    ok, error = provider.fetch_remote(repo, refs=("origin/main",))
    assert ok is True, error

    branch_after = _git_stdout(["branch", "--show-current"], repo).strip()
    status_after = _git_stdout(["status", "--porcelain"], repo)
    assert branch_after == branch_before
    assert status_after == status_before

    ahead, behind = provider.partition_commits(
        repo, local_ref="HEAD", remote_ref="origin/main"
    )
    assert local_id in ahead
    assert remote_id in behind

    subjects = {
        commit.subject
        for commit in provider.log(repo, 10, revs=("HEAD", "origin/main"))
    }
    assert {"base", "local only", "remote only"} <= subjects


def test_provider_fetch_remote_delegates_timeout_to_hook(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plugin = BareGitPlugin()
    timeouts: list[int | None] = []

    def run(args: list[str], cwd: str, *, timeout: int | None = None) -> CommandOutput:
        del args, cwd
        timeouts.append(timeout)
        return CommandOutput(0, "", "")

    monkeypatch.setattr(plugin, "_run", run)
    pm = pluggy.PluginManager("sase_vcs")
    pm.add_hookspecs(VCSHookSpec)
    pm.register(plugin)
    provider = VCSPluginManager(pm)

    ok, error = provider.fetch_remote("/repo", refs=("origin/main",), timeout=7)

    assert ok is True
    assert error is None
    assert timeouts == [7]


def test_remote_log_ref_returns_none_without_origin(repo: str) -> None:
    assert BareGitPlugin().vcs_resolve_remote_log_ref(repo, None) is None


def test_vcs_log_empty_repo_returns_empty(repo: str) -> None:
    # A repo with no commits: `git log` fails (no HEAD); the hook surfaces
    # that as a VCSOperationError rather than a silent empty list.
    from sase.vcs_provider import VCSOperationError

    with pytest.raises(VCSOperationError):
        _bare_git_log(repo, 10)


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
    commits = provider.log(cwd=repo, limit=10, authors=("nobody-matches-this",))

    assert commits == []


def test_provider_repo_stats_delegates_to_hook(repo: str) -> None:
    _commit(repo, "a.txt", "only commit")

    provider = _make_git_provider()
    stats = provider.repo_stats(cwd=repo)

    assert stats.total_commits == 1
    assert stats.last_commit is not None
    assert stats.last_commit.subject == "only commit"
