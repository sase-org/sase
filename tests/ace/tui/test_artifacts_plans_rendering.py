"""List and detail rendering coverage for document-only Plans."""

from __future__ import annotations

from pathlib import Path

from rich.console import Console

from sase.ace.tui.widgets.artifacts.plans_detail import (
    active_plan_properties_header,
    archive_properties_header,
)
from sase.ace.tui.widgets.artifacts.plans_rendering import (
    active_plan_text,
    archive_text,
    build_plans_status,
    proposal_text,
)
from tests.ace.tui._artifacts_plans_helpers import _snapshot


def _render(renderable: object) -> str:
    console = Console(width=120, color_system=None)
    with console.capture() as capture:
        console.print(renderable)
    return capture.get()


def test_rows_render_plan_metadata_and_owning_bead(tmp_path: Path) -> None:
    snapshot = _snapshot(tmp_path)
    labels = (
        proposal_text(snapshot.proposals[0]),
        active_plan_text(snapshot.active[0]),
        archive_text(snapshot.archive[0].match),
    )

    assert all(label.no_wrap and "\n" not in label.plain for label in labels)
    assert "Active rollout  epic  alpha-1" in labels[1].plain
    assert "in progress" in labels[1].plain
    assert "Archived rollout  epic  done" in labels[2].plain


def test_detail_headers_keep_document_properties_and_link_owner(tmp_path: Path) -> None:
    snapshot = _snapshot(tmp_path)
    active = _render(
        active_plan_properties_header(snapshot.active[0], project_name="Alpha")
    )
    archived = _render(
        archive_properties_header(
            snapshot.archive[0].match,
            project_name="Alpha",
            owner=snapshot.bead_plan_links[("alpha", "alpha-closed")],
        )
    )

    assert "Active rollout" in active
    assert "Owning bead" in active and "alpha-1" in active
    assert "Design reference" in active
    assert "alpha-closed" in archived
    assert "Description" not in active
    assert "Dependencies" not in active


def test_status_summary_reports_only_three_document_sections(tmp_path: Path) -> None:
    text = build_plans_status(
        _snapshot(tmp_path),
        loading=False,
        load_error=None,
    ).plain

    assert text == "1 proposals  ·  1 active  ·  1 archived"
    assert "tasks" not in text and "epics" not in text and "phases" not in text
