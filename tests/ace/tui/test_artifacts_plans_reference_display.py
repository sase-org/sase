"""The Plans pane shows a plan reference and where it currently resolves."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from rich.console import Console

from sase.ace.tui.widgets.artifacts import plans_detail, plans_filtering
from sase.ace.tui.widgets.artifacts.plans_data import (
    LinkedPlanDocument,
    PlansSnapshot,
    ProjectIssue,
)
from tests.ace.tui._artifacts_plans_helpers import _snapshot


def _render_detail(renderable: object) -> str:
    console = Console(width=120, color_system=None)
    with console.capture() as capture:
        console.print(renderable)
    return capture.get()


def _snapshot_with_design(
    tmp_path: Path,
    *,
    reference: str,
    resolved_path: str,
    error: str | None = None,
) -> tuple[PlansSnapshot, ProjectIssue]:
    snapshot = _snapshot(tmp_path)
    epic = replace(snapshot.epics[0].issue, design=reference)
    document = LinkedPlanDocument(
        reference=reference,
        path=resolved_path,
        content="",
        frontmatter={},
        body="",
        error=error,
        signature=None if error else (1, 1, 1, 1),
    )
    snapshot = replace(
        snapshot,
        epics=(ProjectIssue("alpha", epic),),
        phases_by_epic={
            ("alpha", epic.id): snapshot.phases_by_epic[("alpha", epic.id)]
        },
        linked_plan_documents={("alpha", epic.id): document},
    )
    return snapshot, ProjectIssue("alpha", epic)


def test_properties_show_the_reference_above_its_resolved_path(
    tmp_path: Path,
) -> None:
    resolved = "/plans/202607/durable.md"
    snapshot, epic = _snapshot_with_design(
        tmp_path,
        reference="plans:202607/durable.md",
        resolved_path=resolved,
    )

    detail = _render_detail(
        plans_detail.bead_properties_header(
            epic.issue,
            snapshot,
            project="alpha",
            project_name="Alpha",
        )
    )

    assert "Plan reference plans:202607/durable.md" in " ".join(detail.split())
    assert f"Resolved plan {resolved}" in " ".join(detail.split())


def test_properties_render_an_unresolved_link_as_such(tmp_path: Path) -> None:
    snapshot, epic = _snapshot_with_design(
        tmp_path,
        reference="plans:202607/gone.md",
        resolved_path="/plans/202607/gone.md",
        error="Linked plan unavailable: file not found.",
    )

    detail = " ".join(
        _render_detail(
            plans_detail.bead_properties_header(
                epic.issue,
                snapshot,
                project="alpha",
                project_name="Alpha",
            )
        ).split()
    )

    assert "Plan reference plans:202607/gone.md" in detail
    assert "Resolved plan (unresolved: no plan file found)" in detail
    assert "gone.md (unresolved" not in detail


def test_preview_markdown_reports_the_reference_and_resolution(
    tmp_path: Path,
) -> None:
    resolved = "/plans/202607/durable.md"
    snapshot, epic = _snapshot_with_design(
        tmp_path,
        reference="plans:202607/durable.md",
        resolved_path=resolved,
    )

    preview = plans_detail.bead_preview_markdown(
        epic.issue,
        snapshot,
        project="alpha",
    )

    assert "**Plan reference:** plans:202607/durable.md" in preview
    assert f"**Resolved plan:** → {resolved}" in preview


def test_preview_markdown_marks_a_missing_plan(tmp_path: Path) -> None:
    snapshot, epic = _snapshot_with_design(
        tmp_path,
        reference="plans:202607/gone.md",
        resolved_path="",
        error="Linked plan unavailable: file not found.",
    )

    preview = plans_detail.bead_preview_markdown(
        epic.issue,
        snapshot,
        project="alpha",
    )

    assert "**Resolved plan:** → (unresolved: no plan file found)" in preview


def test_resolved_plan_path_is_none_when_the_link_is_broken(
    tmp_path: Path,
) -> None:
    resolved = "/plans/202607/durable.md"
    snapshot, epic = _snapshot_with_design(
        tmp_path,
        reference="plans:202607/durable.md",
        resolved_path=resolved,
    )
    broken, broken_epic = _snapshot_with_design(
        tmp_path,
        reference="plans:202607/gone.md",
        resolved_path="/plans/202607/gone.md",
        error="Linked plan unavailable: file not found.",
    )

    assert (
        plans_detail.resolved_plan_path(epic.issue, snapshot, project="alpha")
        == resolved
    )
    assert (
        plans_detail.resolved_plan_path(
            broken_epic.issue,
            broken,
            project="alpha",
        )
        is None
    )


def test_filter_matches_both_the_reference_and_the_resolved_path(
    tmp_path: Path,
) -> None:
    resolved = "/plans/202607/durable.md"
    snapshot, epic = _snapshot_with_design(
        tmp_path,
        reference="plans:202607/durable.md",
        resolved_path=resolved,
    )

    index = plans_filtering.build_plan_filter_index(snapshot)
    record = next(item for item in index.records if item.identity == epic.issue.id)

    assert any("plans:202607/durable.md" in value for value in record.haystack)
    assert any(resolved.casefold() in value for value in record.haystack)
