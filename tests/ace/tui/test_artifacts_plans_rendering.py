"""List and detail rendering coverage for document-only Plans."""

from __future__ import annotations

from pathlib import Path

from rich.console import Console

from sase.ace.tui.widgets.artifacts.plans_detail import (
    active_plan_properties_header,
    archive_properties_header,
    provider_detail_fields,
)
from sase.ace.tui.widgets.artifacts.plans_rendering import (
    active_plan_text,
    archive_text,
    build_plans_scope,
    build_plans_status,
    proposal_text,
)
from sase.ace.tui.keymaps import load_keymap_registry
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


def test_detail_headers_follow_provider_declared_fields(tmp_path: Path) -> None:
    snapshot = _snapshot(tmp_path)
    active = _render(
        active_plan_properties_header(
            snapshot.active[0],
            project_name="Alpha",
            detail_fields=("status", "create_time", "tier"),
        )
    )

    status_index = active.index("Status")
    create_index = active.index("Create time")
    tier_index = active.index("Tier")
    title_index = active.index("Title")

    assert status_index < create_index < tier_index < title_index


def test_provider_detail_fields_extracts_declared_order() -> None:
    spec = {
        "ref": {
            "detail": {
                "fields": ["status", "create_time", "status", "", "tags"],
            },
        },
    }

    assert provider_detail_fields(spec) == ("status", "create_time", "tags")


def test_provider_detail_fields_ignores_missing_or_malformed_specs() -> None:
    assert provider_detail_fields(None) == ()
    assert provider_detail_fields({"ref": {"detail": {"fields": "status"}}}) == ()
    assert provider_detail_fields({"ref": {"detail": []}}) == ()


def test_status_summary_reports_only_three_document_sections(tmp_path: Path) -> None:
    text = build_plans_status(
        _snapshot(tmp_path),
        loading=False,
        load_error=None,
    ).plain

    assert text == "1 proposals  ·  1 active  ·  1 archived"
    assert "tasks" not in text and "epics" not in text and "phases" not in text


def test_row_and_scope_renderers_use_the_supplied_accent_not_plans_purple(
    tmp_path: Path,
) -> None:
    """A non-Plan document provider must render its own accent.

    Before the shell phase these renderers hard-coded
    ``ARTIFACTS_ACCENTS["plans"]``, so a Research pane (or any other
    non-Plan document provider) rendered Plans-purple even though its
    descriptor and tab used a different accent.
    """
    snapshot = _snapshot(tmp_path)
    research_accent = "#058D1D"

    labels = (
        proposal_text(snapshot.proposals[0], accent=research_accent),
        active_plan_text(snapshot.active[0], accent=research_accent),
        archive_text(snapshot.archive[0].match, accent=research_accent),
    )
    for label in labels:
        styles = {str(span.style) for span in label.spans}
        assert any(research_accent in style for style in styles)
        assert not any("#AF87FF" in style for style in styles)

    scope = build_plans_scope(
        load_keymap_registry({}),
        project_scope=None,
        project_display_name=None,
        provider_label="Research",
        accent=research_accent,
    )
    scope_styles = {str(span.style) for span in scope.spans}
    assert any(research_accent in style for style in scope_styles)
    assert not any("#AF87FF" in style for style in scope_styles)
