"""Prompt panel section navigation cache behavior."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

from rich.console import Console, Group, RenderableType
from rich.segment import Segment
from rich.style import Style as RichStyle
from rich.text import Text
from textual._context import active_app
from textual.css.styles import RulesMap
from textual.strip import Strip
from textual.style import Style
from textual.visual import RenderOptions, RichVisual, Visual

from sase.ace.tui.widgets.prompt_panel import _section_navigation
from sase.ace.tui.widgets.prompt_panel import AgentPromptPanel
from sase.ace.tui.widgets.prompt_panel._section_navigation import (
    SECTION_MARKER_META_KEY,
    SectionTrackingVisual,
)
from tests.ace.tui.widgets._prompt_panel_section_navigation_helpers import (
    _ConsoleVisual,
    section,
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


def test_section_tracking_visual_uses_supplied_generation_digest(monkeypatch) -> None:
    """The prompt panel can reuse the digest computed during ``update``."""
    panel = AgentPromptPanel()
    panel._section_generation = 1  # noqa: SLF001
    visual = _CountingRichVisual([], renderable=Group(section("IDLE", "body\n")))

    digest = "known-generation-digest"
    monkeypatch.setattr(
        _section_navigation,
        "renderable_content_digest",
        Mock(side_effect=AssertionError("digest should not be recomputed")),
    )

    tracker = SectionTrackingVisual(
        visual,
        panel,
        panel._section_generation,  # noqa: SLF001
        content_digest=digest,
    )

    assert tracker._content_digest == digest  # noqa: SLF001


def _strip_plain(strips: list[Strip]) -> str:
    return "".join(segment.text for strip in strips for segment in strip)


def test_section_tracking_visual_does_not_reuse_cropped_strips_for_taller_paint() -> (
    None
):
    panel = AgentPromptPanel()
    panel._section_generation = 1  # noqa: SLF001
    renderable = Group(
        Text("alpha-cache\n"), Text("bravo-cache\n"), Text("charlie-cache\n")
    )
    tracker = SectionTrackingVisual(_ConsoleVisual(renderable), panel, 1)
    paint = RenderOptions(get_style=lambda _style: Style(), rules={})

    cropped = tracker.render_strips(40, 1, Style(), paint)
    full = tracker.render_strips(40, None, Style(), paint)

    assert "alpha-cache" in _strip_plain(cropped)
    assert "bravo-cache" not in _strip_plain(cropped)
    assert "bravo-cache" in _strip_plain(full)
    assert "charlie-cache" in _strip_plain(full)
    assert len(full) > len(cropped)


def test_constrained_strip_paint_does_not_poison_measured_height() -> None:
    panel = AgentPromptPanel()
    panel._section_generation = 1  # noqa: SLF001
    renderable = Group(
        Text("alpha-height\n"), Text("bravo-height\n"), Text("charlie-height\n")
    )
    tracker = SectionTrackingVisual(_ConsoleVisual(renderable), panel, 1)
    paint = RenderOptions(get_style=lambda _style: Style(), rules={})

    cropped = tracker.render_strips(40, 1, Style(), paint)

    assert len(cropped) == 1
    assert tracker.get_height({}, 40) > 1


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
