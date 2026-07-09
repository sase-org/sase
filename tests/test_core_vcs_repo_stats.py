"""Tests for the VCS repo stats facade."""

from __future__ import annotations

import pytest

import sase.core.vcs_repo_stats_facade as facade
from sase.core.vcs_log_wire import VcsCommitWire
from sase.core.vcs_repo_stats_facade import build_vcs_repo_stats
from sase.core.vcs_repo_stats_wire import VcsRepoStatsWire


def _commit() -> VcsCommitWire:
    return VcsCommitWire(
        full_id="a1b2c3d4",
        short_id="a1b2c3d",
        author_name="Bryan",
        author_email="bryan@example.com",
        timestamp=300,
        subject="feat: stats",
        body="",
    )


def test_build_vcs_repo_stats_parses_aggregate_outputs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commit = _commit()
    monkeypatch.setattr(facade, "parse_git_log", lambda stdout: [commit])
    monkeypatch.setattr(facade, "parse_git_branch_name", lambda stdout: "main")
    monkeypatch.setattr(facade, "parse_git_local_changes", lambda stdout: "M file")

    stats = build_vcs_repo_stats(
        total_commits_stdout="12\n",
        contributors_stdout=(
            "  9\tBryan <bryan@example.com>\n"
            "  3\tAmy <amy@example.com>\n"
            "  1\tBryan <bryan@example.com>\n"
        ),
        last_commit_stdout="raw log",
        branch_stdout="main\n",
        status_stdout=" M file\n",
    )

    assert stats == VcsRepoStatsWire(
        total_commits=12,
        contributors=("Bryan <bryan@example.com>", "Amy <amy@example.com>"),
        last_commit=commit,
        branch="main",
        dirty=True,
    )


def test_build_vcs_repo_stats_handles_empty_repo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(facade, "parse_git_log", lambda stdout: [])
    monkeypatch.setattr(facade, "parse_git_branch_name", lambda stdout: None)
    monkeypatch.setattr(facade, "parse_git_local_changes", lambda stdout: None)

    stats = build_vcs_repo_stats(
        total_commits_stdout="",
        contributors_stdout="",
        last_commit_stdout="",
        branch_stdout="HEAD\n",
        status_stdout="",
    )

    assert stats == VcsRepoStatsWire(
        total_commits=0,
        contributors=(),
        last_commit=None,
        branch=None,
        dirty=False,
    )
