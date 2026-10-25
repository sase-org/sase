"""Unit coverage for the shared per-repo commit breakdown."""

from __future__ import annotations

from dataclasses import replace

from sase.stats.render.repos import (
    _RepoCommitRow,
    RepoHiddenRow,
    repo_commit_breakdown,
)
from tests.stats._project_render_fixtures import (
    empty_range_view,
    one_project_view,
    repo_edge_view,
)


def test_breakdown_counts_only_code_repos() -> None:
    project = one_project_view().projects[0]
    breakdown = repo_commit_breakdown(project, max_rows=20)

    assert breakdown is not None
    assert [
        row.name for row in breakdown.active if isinstance(row, _RepoCommitRow)
    ] == [
        "sase",
        "sase-core",
    ]
    assert "beads" not in {
        row.name for row in breakdown.active if isinstance(row, _RepoCommitRow)
    }


def test_breakdown_needs_two_code_repos_and_a_measured_project_total() -> None:
    project = one_project_view().projects[0]
    one_code_repo = replace(
        project,
        repos=tuple(repo for repo in project.repos if repo.tier == "records")
        + (next(repo for repo in project.repos if repo.tier == "code"),),
    )
    assert repo_commit_breakdown(one_code_repo, max_rows=6) is None
    assert repo_commit_breakdown(replace(project, output=None), max_rows=6) is None
    assert (
        repo_commit_breakdown(
            replace(project, output=replace(project.output, commits=None)), max_rows=6
        )
        is None
    )


def test_breakdown_sort_uses_primary_then_name_for_ties() -> None:
    project = one_project_view().projects[0]
    base = next(repo for repo in project.repos if repo.tier == "code")
    assert base.output is not None
    tied = [
        replace(
            base,
            id="z-linked",
            name="z-linked",
            kind="linked",
            output=replace(base.output, commits=10),
        ),
        replace(
            base,
            id="a-primary",
            name="a-primary",
            kind="primary",
            output=replace(base.output, commits=10),
        ),
        replace(
            base,
            id="a-linked",
            name="a-linked",
            kind="linked",
            output=replace(base.output, commits=10),
        ),
    ]
    total = replace(project.output, commits=30)
    result = repo_commit_breakdown(
        replace(project, output=total, repos=tuple(tied)), max_rows=5
    )

    assert result is not None
    assert [row.name for row in result.active if isinstance(row, _RepoCommitRow)] == [
        "a-primary",
        "a-linked",
        "z-linked",
    ]


def test_breakdown_caps_active_rows_without_hiding_a_single_repo() -> None:
    project = repo_edge_view().projects[0]
    capped = repo_commit_breakdown(project, max_rows=6)
    assert capped is not None
    assert isinstance(capped.active[-1], RepoHiddenRow)
    assert capped.active[-1].hidden_count >= 2
    assert capped.active[-1].commits > 0

    only_one_active = replace(
        project,
        repos=tuple(
            replace(
                repo,
                output=(
                    replace(repo.output, commits=1)
                    if repo.name == "widgets"
                    else replace(repo.output, commits=0)
                    if repo.output is not None
                    else None
                ),
            )
            for repo in project.repos
        ),
    )
    single = repo_commit_breakdown(only_one_active, max_rows=1)
    assert single is not None
    assert len(single.active) == 1
    assert isinstance(single.active[0], _RepoCommitRow)


def test_breakdown_marks_partial_unmeasured_quiet_and_shared_commits() -> None:
    project = repo_edge_view().projects[0]
    breakdown = repo_commit_breakdown(project, max_rows=20)

    assert breakdown is not None
    partial = next(
        row
        for row in breakdown.active
        if isinstance(row, _RepoCommitRow) and row.name == "widgets-core"
    )
    assert partial.partial is True
    assert breakdown.quiet == ("widgets-nvim",)
    assert [row.name for row in breakdown.unmeasured] == [
        "widgets-future",
        "widgets-missing",
    ]
    assert breakdown.shared_commits > 0
    assert round(sum(row.share for row in breakdown.active) * 100) == 100
    assert any(
        isinstance(row, _RepoCommitRow) and 0 < row.share < 0.005
        for row in breakdown.active
    )


def test_empty_range_has_only_quiet_rows() -> None:
    breakdown = repo_commit_breakdown(empty_range_view().projects[0], max_rows=6)

    assert breakdown is not None
    assert breakdown.active == ()
    assert breakdown.quiet == (
        "sase",
        "sase-core",
        "sase-telegram",
        "sase-listen",
        "sase-nvim",
        "shared-lib",
    )
