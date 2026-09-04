"""Prompt panel section target resolution."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import cast
from unittest.mock import patch

from rich.console import Console, Group, RenderableType
from rich.markdown import Markdown
from rich.segment import Segment
from rich.style import Style as RichStyle
from rich.text import Text
from textual._context import active_app
from textual.css.styles import RulesMap
from textual.geometry import Size
from textual.strip import Strip
from textual.style import Style
from textual.visual import RenderOptions, RichVisual, Visual
from textual.widgets import Static

from sase.ace.tui.models._agent_clan_sections import (
    ClanSectionSnapshot,
    aggregate_clan_in_memory,
)
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.fold_state import FoldLevel
from sase.ace.tui.widgets.prompt_panel import _section_navigation
from sase.ace.tui.widgets.prompt_panel import AgentPromptPanel
from sase.ace.tui.widgets.prompt_panel._agent_display_parts import build_header_text
from sase.ace.tui.widgets.prompt_panel._section_navigation import (
    SECTION_MARKER_META_KEY,
    PromptPanelSectionRole,
    PromptPanelSectionTargetKind,
    SectionTrackingVisual,
)
from tests.ace.tui.widgets._prompt_panel_section_navigation_helpers import (
    fold_anchor_section,
    render_panel,
    rendered_section_ids,
    section,
    track_renderable,
)


class _CountingRichVisual(RichVisual):
    """RichVisual stand-in whose measurement path does not render segments."""

    def __init__(
        self,
        strips: list[Strip],
        *,
        renderable: RenderableType | None = None,
    ) -> None:
        self._renderable = (  # noqa: SLF001
            Text("height must delegate to this visual")
            if renderable is None
            else renderable
        )
        self._strips = strips
        self.height_calls = 0
        self.strip_calls = 0

    def get_height(self, rules: RulesMap, width: int) -> int:
        self.height_calls += 1
        return len(self._strips)

    def render_strips(
        self,
        width: int,
        height: int | None,
        style: Style,
        options: RenderOptions,
    ) -> list[Strip]:
        self.strip_calls += 1
        return self._strips


class _CountingVisual(Visual):
    """Visual stand-in that exposes stable strips and call counts."""

    def __init__(self, strips: list[Strip]) -> None:
        self._strips = strips
        self.height_calls = 0
        self.strip_calls = 0

    def get_optimal_width(self, rules: RulesMap, container_width: int) -> int:
        return container_width

    def get_minimal_width(self, rules: RulesMap) -> int:
        return 1

    def get_height(self, rules: RulesMap, width: int) -> int:
        self.height_calls += 1
        return len(self._strips)

    def render_strips(
        self,
        width: int,
        height: int | None,
        style: Style,
        options: RenderOptions,
    ) -> list[Strip]:
        self.strip_calls += 1
        return self._strips


def test_prompt_panel_render_reuses_visual_within_generation() -> None:
    panel = AgentPromptPanel()
    panel.update(Group(Text("first")))

    first = panel.render()
    second = panel.render()

    assert first is second

    panel.update(Group(Text("second")))
    third = panel.render()

    assert third is not first
    assert panel.render() is third


def test_prompt_panel_update_skips_equivalent_content() -> None:
    panel = AgentPromptPanel()
    original = Group(Text("unchanged idle document\n"))
    panel.update(original)
    generation = panel._section_generation  # noqa: SLF001
    visual = panel.render()

    panel.update(Group(Text("unchanged idle document\n")))

    assert panel._section_generation == generation  # noqa: SLF001
    assert panel.render() is visual
    assert panel.content is original


def test_section_tracking_visual_caches_rich_anchor_collection_by_width(
    monkeypatch,
) -> None:
    panel = AgentPromptPanel()
    panel._section_generation = 1  # noqa: SLF001
    renderable = Group(section("FIRST", "body\n"), section("SECOND", "tail\n"))
    visual = _CountingRichVisual([], renderable=renderable)
    tracker = SectionTrackingVisual(
        visual,
        panel,
        panel._section_generation,  # noqa: SLF001
    )
    inspected_segments = 0
    original_resolver = _section_navigation._segment_section_identity  # noqa: SLF001

    def count_resolutions(segment: Segment) -> object:
        nonlocal inspected_segments
        inspected_segments += 1
        return original_resolver(segment)

    monkeypatch.setattr(
        _section_navigation,
        "_segment_section_identity",
        count_resolutions,
    )

    console = Console(width=80)
    token = active_app.set(
        SimpleNamespace(console=console, console_options=console.options)
    )
    try:
        assert tracker.get_height({}, 40) == 0
        first_pass_segment_count = inspected_segments
        assert visual.height_calls == 1
        assert first_pass_segment_count > 0
        assert [anchor.identity for anchor in panel._section_anchors] == [  # noqa: SLF001
            "first",
            "second",
        ]

        tracker.render_strips(
            40,
            1,
            Style(),
            RenderOptions(get_style=lambda _style: Style(), rules={}),
        )
    finally:
        active_app.reset(token)

    assert visual.strip_calls == 1
    assert inspected_segments == first_pass_segment_count


def test_section_tracking_visual_reuses_layout_across_visuals_for_same_content() -> (
    None
):
    panel = AgentPromptPanel()
    panel._section_generation = 1  # noqa: SLF001
    renderable = Group(section("IDLE", "body\n"), section("TAIL", "tail\n"))
    first_visual = _CountingRichVisual([], renderable=renderable)
    first = SectionTrackingVisual(first_visual, panel, 1)
    paint = RenderOptions(get_style=lambda _style: Style(), rules={})
    console = Console(width=80)
    token = active_app.set(
        SimpleNamespace(console=console, console_options=console.options)
    )
    try:
        first.get_height({}, 40)
        first.render_strips(40, 1, Style(), paint)
        assert [anchor.identity for anchor in panel._section_anchors] == [  # noqa: SLF001
            "idle",
            "tail",
        ]

        panel._section_generation = 2  # noqa: SLF001
        panel._section_anchors = ()  # noqa: SLF001
        second_visual = _CountingRichVisual(
            [],
            renderable=Group(section("IDLE", "body\n"), section("TAIL", "tail\n")),
        )
        second = SectionTrackingVisual(second_visual, panel, 2)
        second.get_height({}, 40)
        second.render_strips(40, 1, Style(), paint)
    finally:
        active_app.reset(token)

    assert second_visual.height_calls == 0
    assert second_visual.strip_calls == 0
    assert [anchor.identity for anchor in panel._section_anchors] == [  # noqa: SLF001
        "idle",
        "tail",
    ]


def test_section_tracking_visual_delegates_non_rich_height_without_anchor_collection(
    monkeypatch,
) -> None:
    panel = AgentPromptPanel()
    panel._section_generation = 1  # noqa: SLF001
    visual = _CountingVisual([])
    tracker = SectionTrackingVisual(
        visual,
        panel,
        panel._section_generation,  # noqa: SLF001
    )
    inspected_segments = 0
    original_resolver = _section_navigation._segment_section_identity  # noqa: SLF001

    def count_resolutions(segment: Segment) -> object:
        nonlocal inspected_segments
        inspected_segments += 1
        return original_resolver(segment)

    monkeypatch.setattr(
        _section_navigation,
        "_segment_section_identity",
        count_resolutions,
    )

    assert tracker.get_height({}, 40) == 0
    assert visual.height_calls == 1
    assert inspected_segments == 0


def test_section_tracking_visual_caches_anchor_collection_by_generation_and_width(
    monkeypatch,
) -> None:
    panel = AgentPromptPanel()
    panel._section_generation = 1  # noqa: SLF001
    strips = [
        Strip(
            [
                Segment(
                    "FIRST",
                    RichStyle(meta={SECTION_MARKER_META_KEY: "first"}),
                )
            ]
        ),
        Strip([Segment("body")]),
        Strip(
            [
                Segment(
                    "SECOND",
                    RichStyle(meta={SECTION_MARKER_META_KEY: "second"}),
                )
            ]
        ),
    ]
    visual = _CountingVisual(strips)
    tracker = SectionTrackingVisual(
        visual,
        panel,
        panel._section_generation,  # noqa: SLF001
    )
    inspected_segments = 0
    original_resolver = _section_navigation._segment_section_identity  # noqa: SLF001

    def count_resolutions(segment: Segment) -> object:
        nonlocal inspected_segments
        inspected_segments += 1
        return original_resolver(segment)

    monkeypatch.setattr(
        _section_navigation,
        "_segment_section_identity",
        count_resolutions,
    )

    assert tracker.get_height({}, 40) == len(strips)
    assert visual.height_calls == 1
    assert inspected_segments == 0

    tracker.render_strips(
        40,
        1,
        Style(),
        RenderOptions(get_style=lambda _style: Style(), rules={}),
    )
    first_pass_segment_count = inspected_segments
    assert visual.strip_calls == 1
    assert first_pass_segment_count == 3
    assert [anchor.identity for anchor in panel._section_anchors] == [  # noqa: SLF001
        "first",
        "second",
    ]

    tracker.render_strips(
        40,
        1,
        Style(),
        RenderOptions(get_style=lambda _style: Style(), rules={}),
    )
    assert visual.strip_calls == 1
    assert inspected_segments == first_pass_segment_count


def test_clan_members_section_is_a_navigation_target() -> None:
    container = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="research",
        project_file="/tmp/demo.sase",
        status="RUNNING",
        start_time=datetime(2026, 7, 16, 12, 0, 0),
        agent_clan="research",
        agent_clan_generation="20260716120000",
        is_clan_container=True,
    )
    container.runtime_children = [
        Agent(
            agent_type=AgentType.RUNNING,
            cl_name="research.member",
            project_file="/tmp/demo.sase",
            status="WAITING",
            start_time=datetime(2026, 7, 16, 12, 1, 0),
            raw_suffix="20260716120100",
            agent_name="research.member",
            agent_clan="research",
            agent_clan_generation="20260716120000",
        )
    ]
    member = container.runtime_children[0]
    member.error_message = "failed"
    member.output_variables = {"report": "done"}
    member.step_output = {"meta_summary": "ready"}
    member.epic_bead_id = "sase-demo"
    snapshot = ClanSectionSnapshot(in_memory=aggregate_clan_in_memory(container))
    header, _ = build_header_text(
        container,
        cheap=True,
        clan_snapshot=snapshot,
        clan_fold_level=FoldLevel.EXPANDED,
    )
    panel = render_panel(Group(header), width=80)

    target = panel.resolve_section_target(1, width=80)

    assert rendered_section_ids(header, width=80) == [
        "members",
        "member:research.member",
        "errors",
        "output-variables",
        "workflow-variables",
        "context",
    ]
    assert target.kind is PromptPanelSectionTargetKind.ANCHOR
    assert target.anchor is not None
    assert target.anchor.identity == "members"

    next_target = panel.resolve_section_target(1, width=80)
    assert next_target.kind is PromptPanelSectionTargetKind.ANCHOR
    assert next_target.anchor is not None
    assert next_target.anchor.identity == "errors"


def test_resolve_section_target_skips_fold_only_anchors() -> None:
    def document() -> Group:
        return Group(
            section("ONE", "1\n"),
            fold_anchor_section("roster-row", "row\n", section_id="row-1"),
            section("TWO", "2\n"),
        )

    panel = render_panel(document(), width=40)

    forward_first = panel.resolve_section_target(1, width=40)
    assert forward_first.kind is PromptPanelSectionTargetKind.ANCHOR
    assert forward_first.anchor is not None
    assert forward_first.anchor.identity == "one"

    forward_second = panel.resolve_section_target(1, width=40)
    assert forward_second.kind is PromptPanelSectionTargetKind.ANCHOR
    assert forward_second.anchor is not None
    assert forward_second.anchor.identity == "two"

    panel.prepare_section_document("reverse")
    panel.update(document())
    track_renderable(panel, cast(RenderableType, panel.content), width=40)

    reverse_first = panel.resolve_section_target(-1, width=40)
    assert reverse_first.kind is PromptPanelSectionTargetKind.ANCHOR
    assert reverse_first.anchor is not None
    assert reverse_first.anchor.identity == "two"

    reverse_second = panel.resolve_section_target(-1, width=40)
    assert reverse_second.kind is PromptPanelSectionTargetKind.ANCHOR
    assert reverse_second.anchor is not None
    assert reverse_second.anchor.identity == "one"


def test_resolve_section_target_all_fold_only_anchors_is_empty() -> None:
    panel = render_panel(
        Group(
            fold_anchor_section("roster-row-0", "row0\n", section_id="row-0"),
            fold_anchor_section("roster-row-1", "row1\n", section_id="row-1"),
        ),
        width=40,
    )

    target = panel.resolve_section_target(1, width=40)

    assert target.kind is PromptPanelSectionTargetKind.EMPTY


def test_resolve_section_at_row_still_resolves_fold_only_anchor() -> None:
    panel = render_panel(
        Group(
            section("ONE", "1\n"),
            fold_anchor_section("roster-row", "row\n", section_id="row-1"),
            section("TWO", "2\n"),
        ),
        width=40,
    )
    one, row, two = panel._section_anchors  # noqa: SLF001
    assert one.role is PromptPanelSectionRole.TITLE
    assert row.role is PromptPanelSectionRole.FOLD_ONLY
    assert two.role is PromptPanelSectionRole.TITLE

    assert panel.resolve_section_at_row(row.row, width=40) == "row-1"
    assert panel.resolve_section_at_row(two.row - 1, width=40) == "row-1"
    assert panel.resolve_section_at_row(two.row, width=40) == "two"


def test_render_pass_collects_width_aware_anchors_without_navigation_render() -> None:
    first = section("FIRST", "short\n")
    last = section("LAST", "tail\n")
    renderable = Group(
        first,
        Markdown("A deliberately long Markdown paragraph " * 12),
        last,
    )

    wide = render_panel(renderable, width=72)
    narrow = render_panel(renderable, width=28)
    wide_anchors = wide._section_anchors  # noqa: SLF001
    narrow_anchors = narrow._section_anchors  # noqa: SLF001

    assert [anchor.identity for anchor in wide_anchors] == ["first", "last"]
    assert [anchor.identity for anchor in narrow_anchors] == ["first", "last"]
    assert narrow_anchors[-1].row > wide_anchors[-1].row

    generation = narrow._section_generation  # noqa: SLF001
    target = narrow.resolve_section_target(1, width=28)
    assert target.kind is PromptPanelSectionTargetKind.ANCHOR
    assert target.anchor == narrow_anchors[0]
    assert narrow._section_generation == generation  # noqa: SLF001
    assert narrow.content is renderable


def test_section_target_distinguishes_not_ready_and_empty_documents() -> None:
    panel = AgentPromptPanel()
    panel.prepare_section_document("empty-document")
    panel.update(Group(Text("No marked titles\n")))

    target = panel.resolve_section_target(1, width=40)
    assert target.kind is PromptPanelSectionTargetKind.NOT_READY
    assert target.ready is False

    track_renderable(panel, cast(RenderableType, panel.content), width=40)
    target = panel.resolve_section_target(1, width=40)
    assert target.kind is PromptPanelSectionTargetKind.EMPTY
    assert target.ready is True
    assert panel.active_section_identity is None


def test_resolve_section_at_row_uses_current_render_anchor_cache() -> None:
    panel = render_panel(
        Group(
            Text("header\n"),
            section("ONE", "one\n" * 3),
            section("TWO", "two\n"),
        ),
        width=40,
    )
    first, second = panel._section_anchors  # noqa: SLF001

    assert panel.resolve_section_at_row(first.row - 1, width=40) is None
    assert panel.resolve_section_at_row(first.row, width=40) == "one"
    assert panel.resolve_section_at_row(second.row - 1, width=40) == "one"
    assert panel.resolve_section_at_row(second.row, width=40) == "two"


def test_get_content_height_reserve_uses_last_title_not_trailing_roster_row() -> None:
    content = Group(
        section("ONE", "one\n"),
        Group(
            *(
                fold_anchor_section(f"row {index}", "", section_id=f"row-{index}")
                for index in range(5)
            )
        ),
    )
    panel = AgentPromptPanel(id="agent-prompt-panel")
    panel.prepare_section_document("reserve-test")
    panel.update(content)
    track_renderable(panel, cast(RenderableType, content), width=40)
    panel._section_layout_reserve_enabled = True  # noqa: SLF001

    anchors = {
        anchor.identity: anchor
        for anchor in panel._section_anchors  # noqa: SLF001
    }
    last_title = anchors["one"]
    last_anchor = anchors["row-4"]
    assert last_title.role is PromptPanelSectionRole.TITLE
    assert last_anchor.role is PromptPanelSectionRole.FOLD_ONLY
    assert last_anchor.row > last_title.row

    container = Size(40, 20)
    real_height = 12
    with patch.object(Static, "get_content_height", return_value=real_height):
        height = panel.get_content_height(container, Size(40, 20), 40)

    expected_reserve = max(0, last_title.row + container.height - real_height)
    buggy_reserve_from_trailing_anchor = max(
        0, last_anchor.row + container.height - real_height
    )
    assert expected_reserve < buggy_reserve_from_trailing_anchor
    assert panel._section_layout_reserve == expected_reserve  # noqa: SLF001
    assert height == real_height + expected_reserve


def test_resolve_section_at_row_noops_during_layout_invalidation() -> None:
    panel = render_panel(Group(section("ONE", "body\n")), width=40)
    assert panel.resolve_section_at_row(0, width=40) == "one"

    panel.update(Group(section("ONE", "new body\n")))

    assert panel.resolve_section_at_row(0, width=40) is None


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
