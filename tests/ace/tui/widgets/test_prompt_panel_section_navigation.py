"""Rendered-section navigation for the Agents metadata pane."""

from __future__ import annotations

from datetime import datetime
from itertools import islice
from pathlib import Path
from typing import cast
from unittest.mock import patch

from rich.console import Console, Group, RenderableType
from rich.markdown import Markdown
from rich.segment import Segment
from rich.style import Style as RichStyle
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.css.styles import RulesMap
from textual.strip import Strip
from textual.style import Style
from textual.visual import RenderOptions, Visual

from sase.ace.tui.actions.navigation._basic import BasicNavigationMixin
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.widgets.agent_detail import AgentDetail
from sase.ace.tui.widgets.prompt_panel import AgentPromptPanel
from sase.ace.tui.widgets.prompt_panel._helpers import append_section_heading
from sase.ace.tui.widgets.prompt_panel._section_navigation import (
    SECTION_MARKER_META_KEY,
    SectionTrackingVisual,
)
from sase.ace.tui.widgets.prompt_panel._workflow_render import (
    build_workflow_detail_renderable,
)
from sase.ace.tui.widgets.prompt_panel._workflow_types import WorkflowDetailSnapshot
from tests.ace.tui.widgets._agent_display_helpers import make_artifact_agent


def _section(label: str, body: str, *, section_id: str | None = None) -> Text:
    text = Text()
    append_section_heading(text, label, section_id=section_id)
    text.append(body)
    return text


def _render_panel(
    renderable: object,
    *,
    width: int,
) -> AgentPromptPanel:
    panel = AgentPromptPanel()
    panel.prepare_section_document("test-document")
    panel.update(renderable)
    _track_renderable(panel, cast(RenderableType, renderable), width=width)
    return panel


def _track_renderable(
    panel: AgentPromptPanel,
    renderable: RenderableType,
    *,
    width: int,
) -> None:
    tracker = SectionTrackingVisual(
        _ConsoleVisual(renderable),
        panel,
        panel._section_generation,  # noqa: SLF001
    )
    tracker.get_height({}, width)
    tracker.render_strips(
        width,
        None,
        Style(),
        RenderOptions(get_style=lambda _style: Style(), rules={}),
    )


class _ConsoleVisual(Visual):
    """Small Rich-backed visual for testing the tracking proxy without an app."""

    def __init__(self, renderable: RenderableType) -> None:
        self.renderable = renderable

    def render_strips(
        self,
        width: int,
        height: int | None,
        style: Style,
        options: RenderOptions,
    ) -> list[Strip]:
        console = Console(width=width)
        segments = console.render(self.renderable, console.options.update_width(width))
        return [
            Strip(line)
            for line in islice(
                Segment.split_and_crop_lines(
                    segments,
                    width,
                    include_new_lines=False,
                    pad=False,
                ),
                None,
                height,
            )
        ]

    def get_optimal_width(self, rules: RulesMap, container_width: int) -> int:
        return container_width

    def get_height(self, rules: RulesMap, width: int) -> int:
        return len(
            self.render_strips(
                width, None, Style(), RenderOptions(lambda _: Style(), {})
            )
        )


def _rendered_section_ids(renderable: RenderableType, *, width: int = 60) -> list[str]:
    identities: list[str] = []
    for segment in Console(width=width).render(renderable):
        style = segment.style
        if not isinstance(style, RichStyle) or not style.meta:
            continue
        identity = style.meta.get(SECTION_MARKER_META_KEY)
        if isinstance(identity, str) and identity not in identities:
            identities.append(identity)
    return identities


def test_section_marker_preserves_text_and_ignores_user_matching_content() -> None:
    text = _section("AGENT PROMPT", "AGENT REPLY\n", section_id="agent-prompt")

    assert text.plain == "AGENT PROMPT\nAGENT REPLY\n"
    marked_ranges: list[tuple[int, int, object]] = []
    for span in text.spans:
        style = span.style
        if isinstance(style, RichStyle) and SECTION_MARKER_META_KEY in style.meta:
            marked_ranges.append(
                (span.start, span.end, style.meta[SECTION_MARKER_META_KEY])
            )
    assert marked_ranges == [(0, len("AGENT PROMPT"), "agent-prompt")]


def test_render_pass_collects_width_aware_anchors_without_navigation_render() -> None:
    first = _section("FIRST", "short\n")
    last = _section("LAST", "tail\n")
    renderable = Group(
        first,
        Markdown("A deliberately long Markdown paragraph " * 12),
        last,
    )

    wide = _render_panel(renderable, width=72)
    narrow = _render_panel(renderable, width=28)
    wide_anchors = wide._section_anchors  # noqa: SLF001
    narrow_anchors = narrow._section_anchors  # noqa: SLF001

    assert [anchor.identity for anchor in wide_anchors] == ["first", "last"]
    assert [anchor.identity for anchor in narrow_anchors] == ["first", "last"]
    assert narrow_anchors[-1].row > wide_anchors[-1].row

    generation = narrow._section_generation  # noqa: SLF001
    target, ready = narrow.resolve_section_target(1, width=28)
    assert ready is True
    assert target == narrow_anchors[0]
    assert narrow._section_generation == generation  # noqa: SLF001
    assert narrow.content is renderable


def test_active_section_reconciles_across_same_document_rerender() -> None:
    panel = _render_panel(
        Group(_section("ONE", "1\n"), _section("TWO", "2\n")),
        width=40,
    )
    panel.resolve_section_target(1, width=40)
    panel.resolve_section_target(1, width=40)
    assert panel.active_section_identity == "two"

    panel.update(
        Group(
            _section("ZERO", "0\n"),
            _section("ONE", "now wraps " * 10),
            _section("TWO", "2\n"),
        )
    )
    _track_renderable(panel, cast(RenderableType, panel.content), width=40)
    assert panel.active_section_identity == "two"
    target, ready = panel.resolve_section_target(1, width=40)
    assert ready is True
    assert target is not None and target.identity == "zero"

    panel.prepare_section_document("new-document")
    assert panel.active_section_identity is None


def test_cheap_paint_preserves_section_until_enriched_layout_returns() -> None:
    panel = _render_panel(
        Group(_section("ONE", "1\n"), _section("TWO", "2\n")),
        width=40,
    )
    panel.resolve_section_target(1, width=40)
    panel.resolve_section_target(1, width=40)
    assert panel.active_section_identity == "two"

    panel.preserve_missing_section_on_next_update()
    panel.update(Group(Text("Name: still the same agent\n")))
    _track_renderable(panel, cast(RenderableType, panel.content), width=40)
    assert panel.active_section_identity == "two"

    panel.update(Group(_section("ONE", "1\n"), _section("TWO", "2\n")))
    _track_renderable(panel, cast(RenderableType, panel.content), width=40)
    assert panel.active_section_identity == "two"


def test_regular_agent_and_workflow_render_paths_mark_real_sections(
    tmp_path: Path,
) -> None:
    regular = make_artifact_agent(tmp_path, status="DONE")
    panel = AgentPromptPanel.__new__(AgentPromptPanel)
    with patch.object(panel, "update") as update:
        panel._update_display_impl(regular)  # noqa: SLF001
    assert _rendered_section_ids(update.call_args.args[0]) == [
        "agent-xprompt",
        "agent-prompt",
        "agent-chat",
    ]

    workflow = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="demo",
        project_file="/tmp/demo.sase",
        status="FAILED",
        start_time=datetime(2026, 7, 16, 12, 0, 0),
        workflow="demo_workflow",
        error_message="boom",
    )
    snapshot = WorkflowDetailSnapshot(
        artifacts_path=None,
        workflow_state=None,
        inputs={"target": "tests"},
        meta_raw=None,
        meta_fields=[("Result", "failed")],
        steps=[],
        error=None,
        traceback=None,
        prompt_content="Run the workflow",
        embedded_markers={},
        embedded_meta={},
    )
    workflow_renderable = build_workflow_detail_renderable(workflow, snapshot)
    assert _rendered_section_ids(workflow_renderable) == [
        "workflow-details",
        "error",
        "workflow-variables",
        "inputs",
        "workflow-steps",
        "agent-prompt",
    ]


class _MetadataNavigationApp(BasicNavigationMixin, App[None]):
    current_tab = "agents"
    BINDINGS = [
        Binding("ctrl+j", "next_agent_metadata_section", "Next section"),
        Binding("ctrl+k", "prev_agent_metadata_section", "Previous section"),
        Binding("G", "scroll_to_bottom", "Bottom"),
    ]
    CSS = """
    Screen, #agent-detail-panel, #agent-detail-layout {
        height: 100%;
    }
    #agent-prompt-scroll {
        height: 100%;
        padding: 1 2;
        overflow-y: auto;
    }
    #agent-file-scroll, #agent-tools-scroll {
        display: none;
    }
    #agent-prompt-panel {
        height: auto;
    }
    """

    def compose(self) -> ComposeResult:
        yield AgentDetail(id="agent-detail-panel")


async def test_mounted_actions_cycle_wrap_and_align_every_title_at_top() -> None:
    app = _MetadataNavigationApp()
    async with app.run_test(size=(50, 16)) as pilot:
        panel = app.query_one("#agent-prompt-panel", AgentPromptPanel)
        scroll = app.query_one("#agent-prompt-scroll", VerticalScroll)
        content = Group(
            _section("ONE", "one\n" * 8),
            _section("TWO", "two\n" * 8),
            _section("THREE", "short final body\n"),
        )
        panel.prepare_section_document("forward")
        panel.update(content)
        await pilot.pause()

        anchors = {anchor.identity: anchor.row for anchor in panel._section_anchors}  # noqa: SLF001
        for expected in ("one", "two", "three", "one"):
            await pilot.press("ctrl+j")
            await pilot.pause()
            assert panel.active_section_identity == expected
            assert int(scroll.scroll_y) == panel.virtual_region.y + anchors[expected]

        panel.prepare_section_document("reverse")
        panel.update(content)
        await pilot.pause()
        for expected in ("three", "two", "one", "three"):
            await pilot.press("ctrl+k")
            await pilot.pause()
            assert panel.active_section_identity == expected
            assert int(scroll.scroll_y) == panel.virtual_region.y + anchors[expected]

        # The trailing reserve makes the final title alignable, but ordinary
        # bottom scrolling still stops at the end of real metadata.
        assert (
            int(scroll.scroll_y)
            > int(scroll.max_scroll_y) - panel.section_layout_reserve
        )
        await pilot.press("G")
        await pilot.pause()
        assert int(scroll.scroll_y) == max(
            0,
            int(scroll.max_scroll_y) - panel.section_layout_reserve,
        )


async def test_zero_sections_noop_and_reflow_preserves_active_identity() -> None:
    app = _MetadataNavigationApp()
    async with app.run_test(size=(60, 18)) as pilot:
        panel = app.query_one("#agent-prompt-panel", AgentPromptPanel)
        scroll = app.query_one("#agent-prompt-scroll", VerticalScroll)
        panel.prepare_section_document("empty")
        panel.update(Text("No marked titles\n" * 20))
        await pilot.pause()
        initial_scroll = scroll.scroll_y
        await pilot.press("ctrl+j", "ctrl+k")
        await pilot.pause()
        assert panel.active_section_identity is None
        assert scroll.scroll_y == initial_scroll

        panel.prepare_section_document("reflow")
        panel.update(
            Group(
                _section("FIRST", "wrapped words " * 20),
                _section("SECOND", "tail\n"),
            )
        )
        await pilot.pause()
        await pilot.press("ctrl+j")
        await pilot.pause()
        assert panel.active_section_identity == "first"

        old_second_row = panel._section_anchors[-1].row  # noqa: SLF001
        await pilot.resize_terminal(34, 18)
        await pilot.pause()
        assert panel.active_section_identity == "first"
        assert panel._section_anchors[-1].row > old_second_row  # noqa: SLF001
        await pilot.press("ctrl+j")
        await pilot.pause()
        assert panel.active_section_identity == "second"
        assert int(scroll.scroll_y) == (
            panel.virtual_region.y + panel._section_anchors[-1].row  # noqa: SLF001
        )


async def test_key_during_layout_invalidation_gets_one_after_refresh_retry() -> None:
    app = _MetadataNavigationApp()
    async with app.run_test(size=(50, 16)) as pilot:
        panel = app.query_one("#agent-prompt-panel", AgentPromptPanel)
        panel.prepare_section_document("retry")
        panel.update(Group(_section("FIRST", "body\n"), _section("LAST", "tail\n")))

        app.action_next_agent_metadata_section()
        assert panel.active_section_identity is None
        await pilot.pause()

        assert panel.active_section_identity == "first"
        assert app._agent_metadata_section_retry_scheduled is False  # noqa: SLF001
