"""Breakdown projection contracts for the Projects language view."""

from __future__ import annotations

from sase.stats.project.languages import language_breakdown, repo_code_lines
from tests.stats._project_render_base import code as _code, repo as _repo
from tests.stats._project_render_fixtures import (
    all_projects_view,
    build_view,
    code_pending_view,
    one_project_view,
    unclassified_view,
)
from tests.stats._project_render_projects import sase_project as _sase_project


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


def _unclassified_project_with_repo(
    *, repo_lines: int, other_lines: int, repo_name: str = "mystery"
) -> dict:
    project = _sase_project()
    project["key"] = "edge"
    project["label"] = "edge"
    project["code"] = _code(
        lines=repo_lines,
        tests=int(repo_lines * 0.4),
        docs=50,
        configured=1,
        measured=1,
        languages=[{"name": "python", "files": 10, "lines": repo_lines}]
        if repo_lines
        else [],
        files=10,
    )
    project["repos"] = [
        _repo(
            name=repo_name,
            kind="primary",
            tier="code",
            commits=1,
            files=10,
            lines=repo_lines,
            languages=[{"name": "python", "files": 10, "lines": repo_lines}]
            if repo_lines
            else [],
            other_lines=other_lines,
        )
    ]
    return project


def test_unclassified_threshold_edges() -> None:
    # Below the 1,000-line floor.
    view = build_view(
        projects=[_unclassified_project_with_repo(repo_lines=10_000, other_lines=999)],
        project_refs=("edge",),
    )
    breakdown = language_breakdown(view)
    assert breakdown is not None
    assert breakdown.unclassified == ()

    # Exactly at the floor but below the 10% share (1,000 / 11_112 ≈ 9%).
    view = build_view(
        projects=[
            _unclassified_project_with_repo(repo_lines=11_112, other_lines=1_000)
        ],
        project_refs=("edge",),
    )
    breakdown = language_breakdown(view)
    assert breakdown is not None
    assert breakdown.unclassified == ()

    # Exactly at the floor and at the 10% share.
    view = build_view(
        projects=[
            _unclassified_project_with_repo(repo_lines=10_000, other_lines=1_000)
        ],
        project_refs=("edge",),
    )
    breakdown = language_breakdown(view)
    assert breakdown is not None
    assert len(breakdown.unclassified) == 1
    assert breakdown.unclassified[0].lines == 1_000


def test_unclassified_zero_code_repo_qualifies_on_floor() -> None:
    view = build_view(
        projects=[_unclassified_project_with_repo(repo_lines=0, other_lines=1_000)],
        project_refs=("edge",),
    )
    breakdown = language_breakdown(view)
    assert breakdown is not None
    assert len(breakdown.unclassified) == 1


def test_unclassified_skips_missing_role_counts() -> None:
    project = _unclassified_project_with_repo(repo_lines=1_000, other_lines=40_000)
    repo = project["repos"][0]
    assert repo["snapshot"] is not None
    repo["snapshot"]["role_counts"] = None
    view = build_view(projects=[project], project_refs=("edge",))
    breakdown = language_breakdown(view)
    assert breakdown is not None
    assert breakdown.unclassified == ()


def test_unclassified_portfolio_dedupes_by_repo_id() -> None:
    project_a = _unclassified_project_with_repo(
        repo_lines=1_000, other_lines=40_000, repo_name="shared"
    )
    project_a["key"] = "a"
    project_a["label"] = "a"
    project_b = _unclassified_project_with_repo(
        repo_lines=1_000, other_lines=40_000, repo_name="shared"
    )
    project_b["key"] = "b"
    project_b["label"] = "b"
    # Force the same repo id across projects.
    project_b["repos"][0]["id"] = project_a["repos"][0]["id"]
    view = build_view(projects=[project_a, project_b])
    breakdown = language_breakdown(view)
    assert breakdown is not None
    assert breakdown.many_projects
    assert len(breakdown.unclassified) == 1


def test_unclassified_fixture_guard_fires() -> None:
    view = unclassified_view()
    breakdown = language_breakdown(view)
    assert breakdown is not None
    assert len(breakdown.unclassified) == 1
    assert breakdown.unclassified[0].repo_name == "mystery"
    assert breakdown.unclassified[0].lines == 40_000
    # Existing shared fixture stays below the floor.
    assert language_breakdown(one_project_view()).unclassified == ()  # type: ignore[union-attr]
