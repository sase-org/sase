"""Render-pass section indexing for the Agents metadata panel."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from enum import Enum, auto
from itertools import count
from typing import TYPE_CHECKING, Any, cast
from weakref import ref

from rich.segment import Segment
from rich.text import Text
from textual._context import active_app
from textual.css.styles import RulesMap
from textual.strip import Strip
from textual.style import Style
from textual.visual import RenderOptions, RichVisual, Visual

from ...util.renderable_digest import renderable_content_digest

if TYPE_CHECKING:
    from ._section_view import SectionViewMixin


SECTION_MARKER_META_KEY = "sase_prompt_panel_section"
SECTION_FOLD_ONLY_META_KEY = "sase_prompt_panel_section_fold_only"
DECK_CARD_META_KEY = "sase_deck_card"
DECK_BLOCK_META_KEY = "sase_card_block"


class PromptPanelSectionRole(Enum):
    """Whether a marked span is a navigable title or only a fold anchor."""

    TITLE = auto()
    FOLD_ONLY = auto()
    CARD = auto()
    BLOCK = auto()


@dataclass(frozen=True, slots=True)
class PromptPanelSectionAnchor:
    """One semantic section title and its rendered content row."""

    identity: str
    row: int
    role: PromptPanelSectionRole = PromptPanelSectionRole.TITLE


class PromptPanelSectionTargetKind(Enum):
    """Resolution states for one metadata-section navigation request."""

    NOT_READY = auto()
    EMPTY = auto()
    TOP = auto()
    ANCHOR = auto()


@dataclass(frozen=True, slots=True)
class PromptPanelSectionTarget:
    """A cached navigation result without overloading a missing anchor."""

    kind: PromptPanelSectionTargetKind
    anchor: PromptPanelSectionAnchor | None = None

    @property
    def ready(self) -> bool:
        """Whether the current generation and width have published anchors."""
        return self.kind is not PromptPanelSectionTargetKind.NOT_READY


@dataclass(frozen=True, slots=True)
class _SectionLayoutCacheEntry:
    """Cached height, anchors, and optional paint strips for one document."""

    anchors: tuple[PromptPanelSectionAnchor, ...]
    height: int | None = None
    strips: tuple[Strip, ...] | None = None


_SECTION_LAYOUT_CACHE_MAX_ENTRIES = 8
_section_height_cache: OrderedDict[tuple[str, int], _SectionLayoutCacheEntry] = (
    OrderedDict()
)
_section_strip_cache: OrderedDict[
    tuple[str, int, int | None, str], _SectionLayoutCacheEntry
] = OrderedDict()
_volatile_visual_key_counter = count()


def _textual_style_token(style: Style) -> str:
    """Return a stable paint-style token independent of object identity."""
    return (
        f"{getattr(style, 'foreground', None)}|"
        f"{getattr(style, 'background', None)}|"
        f"{getattr(style, 'bold', None)}|"
        f"{getattr(style, 'dim', None)}|"
        f"{getattr(style, 'italic', None)}"
    )


def _visual_content_digest(visual: Visual) -> str:
    renderable = getattr(visual, "_renderable", None)
    if renderable is not None:
        return renderable_content_digest(renderable)
    return f"visual:{type(visual).__name__}:{next(_volatile_visual_key_counter)}"


def _store_layout(
    cache: OrderedDict,
    key: object,
    entry: _SectionLayoutCacheEntry,
) -> None:
    cache[key] = entry
    cache.move_to_end(key)
    if len(cache) > _SECTION_LAYOUT_CACHE_MAX_ENTRIES:
        cache.popitem(last=False)


class SectionTrackingVisual(Visual):
    """Pass through Textual's normal visual while collecting marked rows."""

    __slots__ = (
        "_anchors_by_key",
        "_content_digest",
        "_generation",
        "_owner",
        "_visual",
    )

    def __init__(
        self,
        visual: Visual,
        owner: SectionViewMixin,
        generation: int,
        *,
        content_digest: str | None = None,
    ) -> None:
        self._visual = visual
        self._owner = ref(owner)
        self._generation = generation
        self._content_digest = (
            content_digest
            if content_digest is not None
            else _visual_content_digest(visual)
        )
        self._anchors_by_key: dict[
            tuple[int, int],
            tuple[PromptPanelSectionAnchor, ...],
        ] = {}

    def render_strips(
        self,
        width: int,
        height: int | None,
        style: Style,
        options: RenderOptions,
    ) -> list[Strip]:
        style_token = _textual_style_token(style)
        strip_key = (self._content_digest, width, height, style_token)
        cached = _section_strip_cache.get(strip_key)
        if cached is not None and cached.strips is not None:
            _section_strip_cache.move_to_end(strip_key)
            self._publish(width=width, anchors=cached.anchors)
            return list(cached.strips)

        try:
            from sase.ace.tui.widgets.decks.panel_view_deferred import get_prebuilt
        except Exception:
            get_prebuilt = None  # type: ignore[assignment]
        if get_prebuilt is not None:
            try:
                prebuilt = get_prebuilt(self._content_digest, width)
            except Exception:
                prebuilt = None
            if prebuilt is not None:
                pre_strips, pre_height, pre_anchors = prebuilt
                # Full prebuilt body: serve it (cropped when requested)
                # without a console render on the loop.
                out = list(pre_strips) if height is None else list(pre_strips[:height])
                _store_layout(
                    _section_strip_cache,
                    strip_key,
                    _SectionLayoutCacheEntry(
                        anchors=pre_anchors,
                        height=len(out),
                        strips=tuple(out),
                    ),
                )
                height_key = (self._content_digest, width)
                height_cached = _section_height_cache.get(height_key)
                if height_cached is None or height_cached.height is None:
                    _store_layout(
                        _section_height_cache,
                        height_key,
                        _SectionLayoutCacheEntry(
                            anchors=pre_anchors, height=pre_height
                        ),
                    )
                else:
                    _section_height_cache.move_to_end(height_key)
                self._publish(width=width, anchors=pre_anchors)
                return out
        strips = self._visual.render_strips(width, height, style, options)
        if isinstance(self._visual, RichVisual):
            height_key_for_anchors = (self._content_digest, width)
            height_cached_for_anchors = _section_height_cache.get(
                height_key_for_anchors
            )
            if (
                height_cached_for_anchors is not None
                and height_cached_for_anchors.anchors
            ):
                _section_height_cache.move_to_end(height_key_for_anchors)
                anchors = height_cached_for_anchors.anchors
            elif height is None or len(strips) < height:
                # Full paint: collect anchors from the strips just built
                # instead of a second console render.
                anchors = self._anchors_for_strips(width=width, strips=strips)
            else:
                # Cropped paint with no published full anchors yet: keep
                # the full-document anchors so navigation rows stay exact.
                anchors = self._anchors_for_rich_visual(width)
        else:
            anchors = self._anchors_for_strips(width=width, strips=strips)
        _store_layout(
            _section_strip_cache,
            strip_key,
            _SectionLayoutCacheEntry(
                anchors=anchors,
                height=len(strips),
                strips=tuple(strips),
            ),
        )
        height_key = (self._content_digest, width)
        height_cached = _section_height_cache.get(height_key)
        measured_full_height = height is None or len(strips) < height
        if measured_full_height and (
            height_cached is None or height_cached.height is None
        ):
            _store_layout(
                _section_height_cache,
                height_key,
                _SectionLayoutCacheEntry(anchors=anchors, height=len(strips)),
            )
        self._publish(width=width, anchors=anchors)
        return strips

    def _anchors_for_strips(
        self,
        *,
        width: int,
        strips: list[Strip],
    ) -> tuple[PromptPanelSectionAnchor, ...]:
        """Return cached anchors, collecting them from the paint strips once."""
        height_key = (self._content_digest, width)
        height_cached = _section_height_cache.get(height_key)
        if height_cached is not None and height_cached.anchors:
            _section_height_cache.move_to_end(height_key)
            return height_cached.anchors
        key = (self._generation, width)
        cached = self._anchors_by_key.get(key)
        if cached is not None:
            return cached
        anchors: list[PromptPanelSectionAnchor] = []
        seen: set[str] = set()
        for row, strip in enumerate(strips):
            for segment in strip:
                resolved = _segment_section_identity(segment)
                if resolved is None:
                    continue
                identity, role = resolved
                if identity not in seen:
                    seen.add(identity)
                    anchors.append(PromptPanelSectionAnchor(identity, row, role))

        cached = tuple(anchors)
        self._anchors_by_key[key] = cached
        existing = _section_height_cache.get(height_key)
        _store_layout(
            _section_height_cache,
            height_key,
            _SectionLayoutCacheEntry(
                anchors=cached,
                height=existing.height if existing is not None else None,
            ),
        )
        return cached

    def _anchors_for_rich_visual(
        self,
        width: int,
    ) -> tuple[PromptPanelSectionAnchor, ...]:
        """Return cached Rich anchors from the uncropped segment stream."""
        height_key = (self._content_digest, width)
        height_cached = _section_height_cache.get(height_key)
        if height_cached is not None and height_cached.anchors:
            _section_height_cache.move_to_end(height_key)
            return height_cached.anchors
        key = (self._generation, width)
        cached = self._anchors_by_key.get(key)
        if cached is not None:
            return cached

        app = active_app.get()
        options = app.console_options.update_width(width).update(highlight=False)
        renderable = cast(Any, self._visual)._renderable  # noqa: SLF001
        segments = app.console.render(renderable, options)
        anchors: list[PromptPanelSectionAnchor] = []
        seen: set[str] = set()
        row = 0
        for segment in segments:
            resolved = _segment_section_identity(segment)
            if resolved is not None:
                identity, role = resolved
                if identity not in seen:
                    seen.add(identity)
                    anchors.append(PromptPanelSectionAnchor(identity, row, role))
            row += segment.text.count("\n")

        cached = tuple(anchors)
        self._anchors_by_key[key] = cached
        existing = _section_height_cache.get(height_key)
        _store_layout(
            _section_height_cache,
            height_key,
            _SectionLayoutCacheEntry(
                anchors=cached,
                height=existing.height if existing is not None else None,
            ),
        )
        return cached

    def get_optimal_width(self, rules: RulesMap, container_width: int) -> int:
        """Delegate optimal-width measurement without changing the visual."""
        return self._visual.get_optimal_width(rules, container_width)

    def get_minimal_width(self, rules: RulesMap) -> int:
        """Delegate minimal-width measurement without changing the visual."""
        return self._visual.get_minimal_width(rules)

    def get_height(self, rules: RulesMap, width: int) -> int:
        """Measure height and publish anchors from one console render."""
        height_key = (self._content_digest, width)
        cached = _section_height_cache.get(height_key)
        if cached is not None and cached.height is not None:
            _section_height_cache.move_to_end(height_key)
            if cached.anchors:
                self._publish(width=width, anchors=cached.anchors)
            return cached.height

        try:
            from sase.ace.tui.widgets.decks.panel_view_deferred import (
                get_prebuilt as _get_prebuilt,
            )
        except Exception:
            _get_prebuilt = None  # type: ignore[assignment]
        if _get_prebuilt is not None:
            try:
                prebuilt = _get_prebuilt(self._content_digest, width)
            except Exception:
                prebuilt = None
            if prebuilt is not None:
                _, pre_height, pre_anchors = prebuilt
                _store_layout(
                    _section_height_cache,
                    height_key,
                    _SectionLayoutCacheEntry(anchors=pre_anchors, height=pre_height),
                )
                if pre_anchors:
                    self._publish(width=width, anchors=pre_anchors)
                return pre_height

        if type(self._visual) is RichVisual:
            single = self._measure_rich_height_and_anchors(width)
            if single is not None:
                single_height, single_anchors = single
                _store_layout(
                    _section_height_cache,
                    height_key,
                    _SectionLayoutCacheEntry(
                        anchors=single_anchors, height=single_height
                    ),
                )
                if single_anchors:
                    self._publish(width=width, anchors=single_anchors)
                return single_height

        height = self._visual.get_height(rules, width)
        anchors: tuple[PromptPanelSectionAnchor, ...] = ()
        if isinstance(self._visual, RichVisual):
            anchors = self._anchors_for_rich_visual(width)
            self._publish(width=width, anchors=anchors)
        _store_layout(
            _section_height_cache,
            height_key,
            _SectionLayoutCacheEntry(anchors=anchors, height=height),
        )
        return height

    def _measure_rich_height_and_anchors(
        self, width: int
    ) -> tuple[int, tuple[PromptPanelSectionAnchor, ...]] | None:
        """Return ``(height, anchors)`` from one ``Console.render`` pass."""
        try:
            renderable = cast(Any, self._visual)._renderable  # noqa: SLF001
        except Exception:
            return None
        if isinstance(renderable, Text):
            return None
        try:
            app = active_app.get()
            options = app.console_options.update_width(width).update(highlight=False)
            segments = app.console.render(renderable, options)
        except Exception:
            return None
        try:
            anchors: list[PromptPanelSectionAnchor] = []
            seen: set[str] = set()
            row = 0
            for segment in segments:
                resolved = _segment_section_identity(segment)
                if resolved is not None:
                    identity, role = resolved
                    if identity not in seen:
                        seen.add(identity)
                        anchors.append(PromptPanelSectionAnchor(identity, row, role))
                row += segment.text.count("\n")
            cached = tuple(anchors)
            self._anchors_by_key[(self._generation, width)] = cached
            return row, cached
        except Exception:
            return None

    def _publish(
        self,
        *,
        width: int,
        anchors: tuple[PromptPanelSectionAnchor, ...],
    ) -> None:
        """Publish a complete anchor set if the owning panel still exists."""
        owner = self._owner()
        if owner is not None:
            owner._publish_section_layout(  # noqa: SLF001
                generation=self._generation,
                width=width,
                anchors=anchors,
            )


def _segment_section_identity(
    segment: Segment,
) -> tuple[str, PromptPanelSectionRole] | None:
    style = segment.style
    meta = style.meta if style is not None else None
    if not meta:
        return None
    card_id = meta.get(DECK_CARD_META_KEY)
    if isinstance(card_id, str) and card_id:
        return f"card:{card_id}", PromptPanelSectionRole.CARD
    block_id = meta.get(DECK_BLOCK_META_KEY)
    if isinstance(block_id, str) and block_id:
        return f"block:{block_id}", PromptPanelSectionRole.BLOCK
    identity = meta.get(SECTION_MARKER_META_KEY)
    if not isinstance(identity, str) or not identity:
        return None
    role = (
        PromptPanelSectionRole.FOLD_ONLY
        if meta.get(SECTION_FOLD_ONLY_META_KEY)
        else PromptPanelSectionRole.TITLE
    )
    return identity, role


__all__ = [
    "DECK_BLOCK_META_KEY",
    "DECK_CARD_META_KEY",
    "PromptPanelSectionAnchor",
    "PromptPanelSectionRole",
    "PromptPanelSectionTarget",
    "PromptPanelSectionTargetKind",
    "SECTION_FOLD_ONLY_META_KEY",
    "SECTION_MARKER_META_KEY",
    "SectionTrackingVisual",
]
