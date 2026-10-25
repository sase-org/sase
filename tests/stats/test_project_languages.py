"""Breakdown projection contracts for the Projects language view."""

from __future__ import annotations

from sase.stats.project.languages import language_breakdown, repo_code_lines
from tests.stats._project_render_fixtures import (
    all_projects_view,
    build_view,
    code_pending_view,
    one_project_view,
)


def test_repo_code_lines_prefers_role_counts() -> None:
    view = one_project_view()
    repo = next(item for item in view.projects[0].repos if item.name == "sase")
    assert repo.snapshot is not None
    assert repo.snapshot.role_counts is not None
    source = next(r for r in repo.snapshot.role_counts if r.role == "source")
    tests = next(r for r in repo.snapshot.role_counts if r.role == "tests")
    assert repo_code_lines(repo.snapshot) == source.lines + tests.lines


def test_repo_code_lines_falls_back_to_tracked() -> None:
    view = one_project_view()
    repo = next(item for item in view.projects[0].repos if item.name == "sase")
    assert repo.snapshot is not None
    object.__setattr__(repo.snapshot, "role_counts", None)
    assert repo_code_lines(repo.snapshot) == repo.snapshot.tracked_lines
    assert repo_code_lines(None) is None


def test_parent_totals_come_from_rust_aggregates() -> None:
    view = one_project_view()
    breakdown = language_breakdown(view)
    assert breakdown is not None
    assert breakdown.total_lines == view.projects[0].code.code_lines
    assert breakdown.total_files == view.projects[0].code.code_files
    by_id = {row.language: row for row in breakdown.rows if row.language is not None}
    for lang in view.projects[0].code.languages:
        if lang.lines == 0:
            continue
        assert by_id[lang.name].lines == lang.lines
        assert by_id[lang.name].files == lang.files


def test_ordering_and_tie_breaks() -> None:
    view = one_project_view()
    breakdown = language_breakdown(view)
    assert breakdown is not None
    known = [row for row in breakdown.rows if row.language is not None]
    assert known == sorted(
        known, key=lambda row: (-row.lines, -row.files, row.language or "")
    )


def test_slices_per_repo() -> None:
    view = one_project_view()
    breakdown = language_breakdown(view)
    assert breakdown is not None
    python = next(row for row in breakdown.rows if row.language == "python")
    assert len(python.slices) == 6
    assert python.slices == tuple(
        sorted(
            python.slices,
            key=lambda item: (
                -item.lines,
                -item.files,
                item.project_label.casefold(),
                item.repo_name.casefold(),
                item.repo_id,
            ),
        )
    )
    rust = next(row for row in breakdown.rows if row.language == "rust")
    assert len(rust.slices) == 1
    assert rust.slices[0].repo_name == "sase-core"


def test_unknown_row_project_and_repo() -> None:
    view = one_project_view()
    breakdown = language_breakdown(view)
    assert breakdown is not None
    unknown = next(row for row in breakdown.rows if row.language is None)
    assert unknown.lines == 1_234
    assert unknown.files == 11
    assert {item.repo_name for item in unknown.slices} == {"sase", "sase-listen"}


def test_zero_line_languages() -> None:
    view = one_project_view()
    breakdown = language_breakdown(view)
    assert breakdown is not None
    assert [(item.language, item.files) for item in breakdown.zero_languages] == [
        ("diff", 3)
    ]
    assert all(row.language != "diff" for row in breakdown.rows)


def test_unmeasured_repos() -> None:
    view = one_project_view()
    breakdown = language_breakdown(view)
    assert breakdown is not None
    assert [(item.repo_name, item.reason) for item in breakdown.unmeasured] == [
        ("missing", "not cloned")
    ]


def test_overlap_lines_portfolio() -> None:
    view = all_projects_view()
    breakdown = language_breakdown(view)
    assert breakdown is not None
    assert breakdown.overlap_lines == 10_000
    single = language_breakdown(one_project_view())
    assert single is not None
    assert single.overlap_lines == 0


def test_portfolio_owner_labels() -> None:
    view = all_projects_view()
    breakdown = language_breakdown(view)
    assert breakdown is not None
    assert breakdown.many_projects
    python = next(row for row in breakdown.rows if row.language == "python")
    assert {item.project_label for item in python.slices} == {"sase", "bob-cli"}


def test_none_for_pending_or_unavailable() -> None:
    assert language_breakdown(code_pending_view()) is None
    view = one_project_view()
    project = view.projects[0]
    object.__setattr__(project, "code", None)
    assert language_breakdown(view) is None
