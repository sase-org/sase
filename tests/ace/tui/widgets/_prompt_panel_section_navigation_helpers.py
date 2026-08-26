"""Helpers for prompt panel section navigation tests."""

from __future__ import annotations

from itertools import islice
from typing import cast

from rich.console import Console, RenderableType
from rich.segment import Segment
from rich.style import Style as RichStyle
from rich.text import Text
from textual.css.styles import RulesMap
from textual.strip import Strip
from textual.style import Style
from textual.visual import RenderOptions, Visual

from sase.ace.tui.widgets.prompt_panel import AgentPromptPanel
from sase.ace.tui.widgets.prompt_panel._helpers import (
    append_fold_anchor,
    append_section_heading,
)
from sase.ace.tui.widgets.prompt_panel._section_navigation import (
    SECTION_MARKER_META_KEY,
    SectionTrackingVisual,
)


def section(label: str, body: str, *, section_id: str | None = None) -> Text:
    text = Text()
    append_section_heading(text, label, section_id=section_id)
    text.append(body)
    return text


def fold_anchor_section(label: str, body: str, *, section_id: str) -> Text:
    text = Text()
    append_fold_anchor(text, Text(label), section_id=section_id)
    text.append(body)
    return text


def render_panel(
    renderable: object,
    *,
    width: int,
) -> AgentPromptPanel:
    panel = AgentPromptPanel()
    panel.prepare_section_document("test-document")
    panel.update(renderable)
    track_renderable(panel, cast(RenderableType, renderable), width=width)
    return panel


def track_renderable(
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


def rendered_section_ids(renderable: RenderableType, *, width: int = 60) -> list[str]:
    identities: list[str] = []
    for segment in Console(width=width).render(renderable):
        style = segment.style
        if not isinstance(style, RichStyle) or not style.meta:
            continue
        identity = style.meta.get(SECTION_MARKER_META_KEY)
        if isinstance(identity, str) and identity not in identities:
            identities.append(identity)
    return identities
