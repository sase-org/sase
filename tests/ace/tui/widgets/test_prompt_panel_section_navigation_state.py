"""Prompt panel section navigation active-state behavior."""

from __future__ import annotations

from typing import cast

from rich.console import Group, RenderableType
from rich.text import Text

from sase.ace.tui.widgets.prompt_panel._section_navigation import (
    PromptPanelSectionTargetKind,
)
from tests.ace.tui.widgets._prompt_panel_section_navigation_helpers import (
    render_panel,
    section,
    track_renderable,
)


def test_active_section_reconciles_across_same_document_rerender() -> None:
    panel = render_panel(
        Group(section("ONE", "1\n"), section("TWO", "2\n")),
        width=40,
    )
    panel.resolve_section_target(1, width=40)
    panel.resolve_section_target(1, width=40)
    assert panel.active_section_identity == "two"

    panel.update(
        Group(
            section("ZERO", "0\n"),
            section("ONE", "now wraps " * 10),
            section("TWO", "2\n"),
        )
    )
    track_renderable(panel, cast(RenderableType, panel.content), width=40)
    assert panel.active_section_identity == "two"
    target = panel.resolve_section_target(1, width=40)
    assert target.kind is PromptPanelSectionTargetKind.TOP
    assert target.anchor is None
    assert panel.active_section_identity is None

    target = panel.resolve_section_target(1, width=40)
    assert target.kind is PromptPanelSectionTargetKind.ANCHOR
    assert target.anchor is not None and target.anchor.identity == "zero"

    panel.prepare_section_document("new-document")
    assert panel.active_section_identity is None


def test_section_target_boundaries_cycle_through_top_in_both_directions() -> None:
    panel = render_panel(
        Group(
            section("ONE", "1\n"),
            section("TWO", "2\n"),
            section("THREE", "3\n"),
        ),
        width=40,
    )

    forward = [panel.resolve_section_target(1, width=40) for _ in range(5)]
    assert [target.kind for target in forward] == [
        PromptPanelSectionTargetKind.ANCHOR,
        PromptPanelSectionTargetKind.ANCHOR,
        PromptPanelSectionTargetKind.ANCHOR,
        PromptPanelSectionTargetKind.TOP,
        PromptPanelSectionTargetKind.ANCHOR,
    ]
    assert [
        target.anchor.identity if target.anchor is not None else None
        for target in forward
    ] == ["one", "two", "three", None, "one"]

    panel.prepare_section_document("reverse-document")
    reverse = [panel.resolve_section_target(-1, width=40) for _ in range(5)]
    assert [target.kind for target in reverse] == [
        PromptPanelSectionTargetKind.ANCHOR,
        PromptPanelSectionTargetKind.ANCHOR,
        PromptPanelSectionTargetKind.ANCHOR,
        PromptPanelSectionTargetKind.TOP,
        PromptPanelSectionTargetKind.ANCHOR,
    ]
    assert [
        target.anchor.identity if target.anchor is not None else None
        for target in reverse
    ] == ["three", "two", "one", None, "three"]


def test_single_section_cycles_to_top_in_both_directions() -> None:
    panel = render_panel(Group(section("ONLY", "body\n")), width=40)

    for direction in (1, -1):
        target = panel.resolve_section_target(direction, width=40)
        assert target.kind is PromptPanelSectionTargetKind.ANCHOR
        assert target.anchor is not None and target.anchor.identity == "only"

        target = panel.resolve_section_target(direction, width=40)
        assert target.kind is PromptPanelSectionTargetKind.TOP
        assert panel.active_section_identity is None


def test_top_waypoint_survives_same_document_rerender() -> None:
    panel = render_panel(
        Group(section("ONE", "1\n"), section("TWO", "2\n")),
        width=40,
    )
    panel.resolve_section_target(1, width=40)
    panel.resolve_section_target(1, width=40)
    target = panel.resolve_section_target(1, width=40)
    assert target.kind is PromptPanelSectionTargetKind.TOP

    panel.update(
        Group(
            Text("New unmarked header\n"),
            section("ONE", "now wraps " * 10),
            section("TWO", "2\n"),
        )
    )
    track_renderable(panel, cast(RenderableType, panel.content), width=40)
    assert panel.active_section_identity is None

    target = panel.resolve_section_target(-1, width=40)
    assert target.kind is PromptPanelSectionTargetKind.ANCHOR
    assert target.anchor is not None and target.anchor.identity == "two"


def test_cheap_paint_preserves_section_until_enriched_layout_returns() -> None:
    panel = render_panel(
        Group(section("ONE", "1\n"), section("TWO", "2\n")),
        width=40,
    )
    panel.resolve_section_target(1, width=40)
    panel.resolve_section_target(1, width=40)
    assert panel.active_section_identity == "two"

    panel.preserve_missing_section_on_next_update()
    panel.update(Group(Text("Name: still the same agent\n")))
    track_renderable(panel, cast(RenderableType, panel.content), width=40)
    assert panel.active_section_identity == "two"

    panel.update(Group(section("ONE", "1\n"), section("TWO", "2\n")))
    track_renderable(panel, cast(RenderableType, panel.content), width=40)
    assert panel.active_section_identity == "two"
